"""Classic RAOP receiver with isolated session sockets, keys and decoder."""

import asyncio
import logging
import math
import plistlib
import socket
import threading
import time
from contextlib import suppress
from urllib.parse import urlsplit

from Crypto.PublicKey import ECC

from miairx.protocols.airplay.ap2 import FORMATS, RealtimeSession, parse_plist
from miairx.protocols.airplay.audio import AudioStreamServer
from miairx.protocols.airplay.crypto import AirplayCrypto
from miairx.protocols.airplay.decoder import AudioDecoder, UnsupportedAudioError
from miairx.protocols.airplay.fairplay import FairPlayError, FairPlaySession
from miairx.protocols.airplay.hap import HAPChannelError, TransientPairing, read_tlv, write_tlv
from miairx.protocols.airplay.legacy_pairing import LegacyPairing, PairingError
from miairx.protocols.airplay.mdns import AirplayMdns
from miairx.protocols.airplay.receiver import Receiver
from miairx.protocols.airplay.rtsp import extract_request, response

log = logging.getLogger(__name__)
PUBLIC = (
    "OPTIONS, GET, POST, ANNOUNCE, SETUP, RECORD, FLUSH, TEARDOWN, GET_PARAMETER, SET_PARAMETER"
)


class AirplayServer:
    def __init__(
        self,
        hostname,
        device_name,
        shared_zeroconf=None,
        speaker_hardware="",
        rtsp_port=0,
        audio_port=0,
    ):
        self.hostname, self.device_name = hostname, device_name
        self.speaker_hardware = speaker_hardware
        self.device_id = AirplayCrypto.generate_device_id()
        self.rtsp_port = rtsp_port
        self._fixed_ports = bool(rtsp_port)
        self._audio_server = AudioStreamServer(hostname, port=audio_port, audio_format="wav")
        self._mdns = AirplayMdns(hostname, device_name, self.device_id, 0, shared_zeroconf)
        self._running = False
        self._server_socket = None
        self._server_thread = None
        self._clients = set()
        self._client_threads = set()
        self._client_lock = threading.Lock()
        self._hap_budget = {}
        self._session_lock = threading.Lock()
        self._receiver = None
        self._ap2_session = None
        self._session_active = False
        # Process-lifetime identity; no persistent trust store or PIN pairing claimed.
        self._signing_key = ECC.generate(curve="Ed25519")
        self.on_play_start = self.on_play_stop = self.on_volume_change = None

    @property
    def audio_port(self):
        return self._audio_server.port

    def runtime_status(self):
        """Expose counters and ports only, never pairing or session secrets."""
        receiver = self._receiver
        ap2 = self._ap2_session
        clock = getattr(receiver, "clock", None)
        return {
            "running": self._running,
            "state": "playing" if self._session_active else "connected" if receiver else "idle",
            "protocol": ("ap2_realtime" if ap2 else "raop") if receiver else None,
            "rtsp_port": self.rtsp_port,
            "audio_port": self.audio_port,
            "event_port": ap2.events.port if ap2 else None,
            "retransmit_requests": getattr(receiver, "retransmit_requests", 0),
            "discontinuities": getattr(receiver, "discontinuities", 0),
            "timing": {
                "measured": bool(clock and clock.fresh),
                "samples": clock.samples if clock else 0,
                "rtt_ms": round(clock.rtt * 1000, 2) if clock and clock.fresh else None,
            },
            "packets": {
                name: getattr(receiver, name, 0)
                for name in ("received", "decoded", "lost", "invalid")
            },
        }

    async def start(self):
        try:
            await self._audio_server.start()
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind(("0.0.0.0", self.rtsp_port))
            self._server_socket.listen(5)
            self._server_socket.settimeout(0.5)
            self.rtsp_port = self._server_socket.getsockname()[1]
            self._mdns.update_port(self.rtsp_port)
            self._running = True
            self._server_thread = threading.Thread(target=self._run_server, daemon=True)
            self._server_thread.start()
            self._mdns.start()
        except Exception:
            self._running = False
            if self._server_socket:
                self._server_socket.close()
            await self._audio_server.stop()
            raise
        log.info(
            "AirPlay classic %s: RTSP/TCP+RTP/UDP=%d HTTP/TCP+RTCP/UDP=%d",
            self.device_name,
            self.rtsp_port,
            self.audio_port,
        )

    async def stop(self):
        self._running = False
        self._mdns.stop()
        if self._server_socket:
            self._server_socket.close()
        with self._client_lock:
            clients = list(self._clients)
        for client in clients:
            with suppress(OSError):
                client.shutdown(socket.SHUT_RDWR)
            client.close()
        if self._server_thread:
            self._server_thread.join(timeout=1)
        with self._client_lock:
            threads = list(self._client_threads)
        await asyncio.gather(*(asyncio.to_thread(t.join, 1) for t in threads))
        if self._receiver:
            self._receiver.close()
        await self._audio_server.stop()

    def _run_server(self):
        while self._running:
            try:
                client, addr = self._server_socket.accept()
                client.settimeout(30)
                with self._client_lock:
                    if len(self._clients) >= 8:
                        client.close()
                        continue
                    self._clients.add(client)
                thread = threading.Thread(
                    target=self._handle_client, args=(client, addr), daemon=True
                )
                with self._client_lock:
                    self._client_threads.add(thread)
                thread.start()
            except TimeoutError:
                continue
            except OSError:
                break

    def _handle_client(self, client, addr):
        decoder = key = iv = receiver = None
        owns_session = False
        playing = False
        volume_db = 0.0
        buffer = b""
        cseq = "0"
        version = "RTSP/1.0"
        pairing = LegacyPairing(self._signing_key)
        fairplay = FairPlaySession()
        hap = TransientPairing()
        channel = None
        ap2 = None

        def send_bytes(data):
            client.sendall(channel.encrypt(data) if channel else data)

        try:
            while self._running:
                request, buffer = extract_request(buffer)
                if request is None:
                    try:
                        chunk = client.recv(8192)
                    except TimeoutError:
                        if receiver and playing and time.monotonic() - receiver.last_audio < 30:
                            continue
                        break
                    if not chunk:
                        break
                    buffer += channel.feed(chunk) if channel else chunk
                    continue
                cseq = request.headers.get("cseq", "0")
                version = request.version
                method, path = request.method, urlsplit(request.uri).path
                # Only log method/path: SDP keys and binary request bodies are private.
                log.debug("AirPlay request: %s %s", method, path)
                status, headers, body = 200, {}, b""
                upgrade = None
                if method == "OPTIONS":
                    headers["Public"] = PUBLIC
                    challenge = request.headers.get("apple-challenge")
                    if challenge:
                        headers["Apple-Response"] = AirplayCrypto.apple_response(
                            challenge,
                            client.getsockname()[0],
                            self.device_id,
                        )
                elif method == "GET" and path == "/info":
                    headers["Content-Type"] = "application/x-apple-binary-plist"
                    body = plistlib.dumps(
                        {
                            "name": self.device_name,
                            "model": "MiAirX",
                            "deviceID": self.device_id,
                            "sourceVersion": "220.68",
                            "protocolVersion": "1.1",
                            "features": (1 << 9) | (1 << 18) | (1 << 19) | (1 << 20),
                            "audioFormats": [
                                {
                                    "type": 96,
                                    "audioInputFormats": sum(FORMATS),
                                    "audioOutputFormats": sum(FORMATS),
                                }
                            ],
                            "pk": self._signing_key.public_key().export_key(format="raw"),
                        },
                        fmt=plistlib.FMT_BINARY,
                    )
                elif method == "POST":
                    content_type = request.headers.get("content-type", "").split(";")[0].strip()
                    if path == "/pair-pin-start" and request.headers.get("x-apple-hkp") == "4":
                        if channel:
                            status = 455
                    elif path == "/pair-setup" and request.headers.get("x-apple-hkp") == "4":
                        if channel or owns_session:
                            status = 455
                        else:
                            headers["Content-Type"] = "application/pairing+tlv8"
                            if read_tlv(request.body).get(6) == b"\1" and not self._allow_hap(
                                addr[0]
                            ):
                                hap.reset()
                                body = write_tlv({6: b"\2", 7: b"\3", 8: b"\x3c"})
                            else:
                                body = hap.setup(request.body)
                            upgrade = hap.channel
                    elif path == "/fp-setup":
                        headers["Content-Type"] = "application/octet-stream"
                        try:
                            body = fairplay.setup(request.body)
                        except FairPlayError as exc:
                            status = exc.status
                        log.info(
                            "AirPlay FairPlay setup: status=%d bytes=%d", status, len(request.body)
                        )
                    elif (
                        path in ("/pair-setup", "/pair-verify")
                        and content_type != "application/pairing+tlv8"
                        and "x-apple-hkp" not in request.headers
                    ):
                        headers["Content-Type"] = "application/octet-stream"
                        try:
                            body = (
                                pairing.setup(request.body)
                                if path == "/pair-setup"
                                else pairing.verify(request.body)
                            )
                        except PairingError as exc:
                            status = exc.status
                        log.info("AirPlay legacy pairing: %s status=%d", path, status)
                    elif path != "/feedback":
                        status = 501
                        log.warning(
                            "Unsupported AirPlay handshake endpoint: %s; "
                            "HAP/unknown endpoint unavailable (content-type=%s, body-bytes=%d)",
                            path,
                            content_type,
                            len(request.body),
                        )
                    elif ap2 and ap2.configured:
                        headers["Content-Type"] = "application/x-apple-binary-plist"
                        body = plistlib.dumps(
                            {"streams": [{"type": 96, "streamID": ap2.stream_id}]},
                            fmt=plistlib.FMT_BINARY,
                        )
                elif method == "ANNOUNCE":
                    if receiver is not None:
                        status = 455
                    elif not owns_session and not self._session_lock.acquire(blocking=False):
                        status = 453
                    else:
                        owns_session = True
                        try:
                            sdp = request.body.decode("ascii")
                            attrs = dict(
                                line[2:].split(":", 1)
                                for line in sdp.splitlines()
                                if line.startswith("a=") and ":" in line
                            )
                            if "fpaeskey" in attrs and "rsaaeskey" in attrs:
                                raise ValueError("Conflicting session key types")
                            if "fpaeskey" in attrs:
                                new_key = fairplay.decrypt_key(
                                    AirplayCrypto.decode_base64(attrs["fpaeskey"])
                                )
                            else:
                                new_key = (
                                    AirplayCrypto.decrypt_rsa_aes_key(attrs["rsaaeskey"])
                                    if "rsaaeskey" in attrs
                                    else None
                                )
                            new_iv = (
                                AirplayCrypto.decode_base64(attrs["aesiv"])
                                if "aesiv" in attrs
                                else None
                            )
                            if new_key is not None and (new_iv is None or len(new_iv) != 16):
                                raise ValueError("Invalid AES IV")
                            new_decoder = AudioDecoder(sdp)
                            decoder, key, iv = new_decoder, new_key, new_iv
                            self._audio_server.set_audio_params(
                                decoder.sample_rate, decoder.channels
                            )
                        except (ValueError, KeyError, UnicodeError, ImportError) as exc:
                            decoder = key = iv = None
                            status = (
                                exc.status
                                if isinstance(exc, FairPlayError)
                                else 415
                                if isinstance(exc, (UnsupportedAudioError, ImportError))
                                else 400
                            )
                            log.warning("AirPlay ANNOUNCE rejected: %s", type(exc).__name__)
                elif method == "SETUP" and request.body.startswith(b"bplist00"):
                    if channel is None or hap.shared is None:
                        status = 403
                    elif receiver is not None and ap2 is None:
                        status = 455
                    elif not owns_session and not self._session_lock.acquire(blocking=False):
                        status = 453
                    else:
                        owns_session = True
                        try:
                            fields = parse_plist(request.body)
                            if fields.get("timingProtocol", "NTP") not in ("NTP", "None"):
                                raise UnsupportedAudioError("AP2 PTP is not implemented")
                            if ap2 is None:
                                event_port = self.rtsp_port + 100 if self._fixed_ports else 0
                                if event_port > 65535:
                                    raise UnsupportedAudioError("No room for AP2 event port")
                                ap2 = RealtimeSession(
                                    addr[0],
                                    hap.shared,
                                    (self.rtsp_port, self.audio_port),
                                    self._audio_server.write_audio,
                                    self._audio_ready,
                                    event_port=event_port,
                                )
                                receiver = self._receiver = ap2.receiver
                                self._ap2_session = ap2
                            reply = ap2.setup(fields)
                            decoder = receiver.decoder
                            self._audio_server.set_audio_params(
                                decoder.sample_rate, decoder.channels
                            )
                            headers = {
                                "Content-Type": "application/x-apple-binary-plist",
                                "Session": "1",
                            }
                            body = plistlib.dumps(reply, fmt=plistlib.FMT_BINARY)
                        except (ValueError, ImportError, OSError) as exc:
                            status = (
                                415
                                if isinstance(exc, (UnsupportedAudioError, ImportError))
                                else 503
                                if isinstance(exc, OSError)
                                else 400
                            )
                            log.warning("AP2 realtime SETUP rejected: %s", type(exc).__name__)
                elif method == "SETUP":
                    transport = request.headers.get("transport", "")
                    if not owns_session or decoder is None or receiver is not None:
                        status = 455
                    elif not transport.startswith("RTP/AVP/UDP") or "multicast" in transport:
                        status = 461
                    else:
                        params = dict(
                            part.split("=", 1) for part in transport.split(";") if "=" in part
                        )
                        control = int(params.get("control_port", "0"))
                        timing = int(params.get("timing_port", "0"))
                        if not 0 <= control <= 65535 or not 0 <= timing <= 65535:
                            raise ValueError("Invalid control port")
                        receiver = Receiver(
                            addr[0],
                            decoder,
                            key,
                            iv,
                            (self.rtsp_port, self.audio_port),
                            self._audio_server.write_audio,
                            self._audio_ready,
                        )
                        receiver.client_control = control
                        receiver.client_timing = timing
                        receiver.listen()
                        self._receiver = receiver
                        rtp, rtcp = receiver.ports
                        headers = {
                            "Transport": "RTP/AVP/UDP;unicast;mode=record;"
                            f"server_port={rtp};control_port={rtcp};timing_port={rtcp}",
                            "Session": "1",
                        }
                elif method == "RECORD":
                    if receiver is None or (ap2 and not ap2.configured):
                        status = 455
                    else:
                        if not playing:
                            sequence = self._sequence(request.headers)
                            timestamp = self._timestamp(request.headers)
                            self._audio_server.start_streaming()
                            receiver.start(sequence, timestamp)
                            self._session_active = playing = True
                        headers = {"Session": "1", "Audio-Latency": "11025"}
                elif method == "FLUSH":
                    if receiver is None:
                        status = 455
                    else:
                        receiver.flush(
                            self._sequence(request.headers), self._timestamp(request.headers)
                        )
                        self._audio_server.clear_audio()
                elif method == "SET_PARAMETER":
                    if not owns_session:
                        status = 455
                    elif request.headers.get("content-type", "").split(";")[0] == "text/parameters":
                        for line in request.body.decode("ascii").splitlines():
                            if line.startswith("volume:"):
                                volume_db = float(line.split(":", 1)[1])
                                if not math.isfinite(volume_db):
                                    raise ValueError("Invalid volume")
                                pct = (
                                    0
                                    if volume_db <= -144
                                    else round(max(0, min(1, (volume_db + 30) / 30)) * 100)
                                )
                                if self.on_volume_change:
                                    self.on_volume_change(pct)
                elif method == "GET_PARAMETER":
                    headers = {"Content-Type": "text/parameters"}
                    body = f"volume: {volume_db:.6f}\r\n".encode("ascii")
                elif method == "TEARDOWN":
                    send_bytes(response(200, cseq, version=version))
                    break
                else:
                    status = 405
                send_bytes(response(status, cseq, headers, body, version=version))
                if upgrade:
                    # M4 is plaintext. Only subsequent bytes use HAP framing,
                    # including encrypted data already pipelined behind M3.
                    channel = upgrade
                    buffer = channel.feed(buffer)
        except HAPChannelError:
            # Never send an unauthenticated plaintext/error oracle on a bad frame.
            log.warning("AirPlay encrypted control authentication failed")
        except (ValueError, UnicodeError):
            with suppress(OSError):
                send_bytes(response(400, cseq, version=version))
        except (OSError, TimeoutError):
            pass
        except Exception:
            log.exception("AirPlay session failed")
        finally:
            pairing.reset()
            fairplay.reset()
            hap.reset()
            if receiver:
                if ap2:
                    ap2.close()
                else:
                    receiver.close()
                if self._receiver is receiver:
                    self._receiver = None
                    self._ap2_session = None
            if owns_session:
                self._audio_server.stop_streaming()
                self._session_active = False
                if playing and self.on_play_stop:
                    try:
                        self.on_play_stop()
                    except Exception:
                        log.exception("AirPlay stop callback failed")
                self._session_lock.release()
            with self._client_lock:
                self._clients.discard(client)
                self._client_threads.discard(threading.current_thread())
            client.close()

    def _allow_hap(self, address):
        now = time.monotonic()
        with self._client_lock:
            times = [t for t in self._hap_budget.get(address, []) if now - t < 60]
            if len(times) >= 5:
                return False
            if address not in self._hap_budget and len(self._hap_budget) >= 256:
                oldest = min(self._hap_budget, key=lambda ip: self._hap_budget[ip][-1])
                del self._hap_budget[oldest]
            self._hap_budget[address] = [*times, now]
            return True

    @staticmethod
    def _sequence(headers):
        for part in headers.get("rtp-info", "").split(";"):
            if part.strip().startswith("seq="):
                seq = int(part.strip()[4:])
                if not 0 <= seq <= 65535:
                    raise ValueError("Invalid RTP sequence")
                return seq
        return None

    @staticmethod
    def _timestamp(headers):
        for part in headers.get("rtp-info", "").split(";"):
            if part.strip().startswith("rtptime="):
                stamp = int(part.strip()[8:])
                if not 0 <= stamp <= 0xFFFFFFFF:
                    raise ValueError("Invalid RTP timestamp")
                return stamp
        return None

    def _audio_ready(self):
        if self.on_play_start:
            self.on_play_start(self._audio_server.stream_url)
