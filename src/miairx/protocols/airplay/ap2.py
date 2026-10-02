"""Experimental single-speaker AP2 realtime/NTP session, no buffered/PTP mode."""

import logging
import plistlib
import secrets
import socket
import threading
from contextlib import suppress

from miairx.protocols.airplay.decoder import AudioDecoder, UnsupportedAudioError
from miairx.protocols.airplay.hap import HAPChannel, derive
from miairx.protocols.airplay.receiver import Receiver
from miairx.protocols.airplay.rtsp import extract_request, response


def parse_plist(body):
    if not 8 <= len(body) <= 65536 or not body.startswith(b"bplist00"):
        raise ValueError("Expected bounded binary plist")
    if len(body) < 40 or int.from_bytes(body[-24:-16], "big") > 1024:
        raise ValueError("Too many plist objects")
    try:
        result = plistlib.loads(body)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("Invalid binary plist") from None
    if not isinstance(result, dict):
        raise ValueError("Expected plist dictionary")
    return result


class EventListener:
    def __init__(self, peer, shared, port):
        self.peer, self.shared = peer, shared
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client = None
        self.stopped = threading.Event()
        try:
            self.socket.bind(("0.0.0.0", port))
            self.socket.listen(1)
            self.socket.settimeout(0.5)
        except Exception:
            self.socket.close()
            raise
        self.port = self.socket.getsockname()[1]
        self.thread = threading.Thread(target=self._run, daemon=True, name="miairx-ap2-events")
        self.thread.start()

    def _run(self):
        while not self.stopped.is_set():
            try:
                client, address = self.socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self.client = client
            try:
                if address[0] != self.peer:
                    continue
                client.settimeout(30)
                channel = HAPChannel(
                    derive(self.shared, "Events-Salt", "Events-Read-Encryption-Key"),
                    derive(self.shared, "Events-Salt", "Events-Write-Encryption-Key"),
                )
                buffer = b""
                while not self.stopped.is_set():
                    request, buffer = extract_request(buffer)
                    if request is None:
                        data = client.recv(8192)
                        if not data:
                            break
                        buffer += channel.feed(data)
                        continue
                    # No remote-control commands implemented: only keepalive.
                    status = (
                        200 if request.method == "OPTIONS" or request.uri == "/feedback" else 501
                    )
                    client.sendall(
                        channel.encrypt(
                            response(
                                status, request.headers.get("cseq", "0"), version=request.version
                            )
                        )
                    )
            except (OSError, ValueError):
                pass
            finally:
                client.close()
                self.client = None

    def close(self):
        self.stopped.set()
        self.socket.close()
        client = self.client
        if client:
            with suppress(OSError):
                client.shutdown(socket.SHUT_RDWR)
            client.close()
        self.thread.join(timeout=1)


# Audio format masks are protocol constants, not a negotiated arbitrary bitmap.
FORMATS = {
    1 << 10: (1, 44100, 1),
    1 << 11: (1, 44100, 2),
    1 << 14: (1, 48000, 1),
    1 << 15: (1, 48000, 2),
    1 << 18: (2, 44100, 2),
    1 << 20: (2, 48000, 2),
}


class RealtimeSession:
    def __init__(self, peer, shared, ports, write_pcm, on_audio, event_port=0):
        self.configured = False
        self.stream_id = secrets.randbits(32)
        self.receiver = Receiver(
            peer, AudioDecoder("a=rtpmap:96 L16/44100/2"), None, None, ports, write_pcm, on_audio
        )
        try:
            self.events = EventListener(peer, shared, event_port)
            self.receiver.listen()
            logging.getLogger(__name__).info(
                "Experimental AP2 event channel: TCP %d", self.events.port
            )
        except Exception:
            self.receiver.close()
            raise

    def setup(self, fields):
        if fields.get("timingProtocol", "NTP") not in ("NTP", "None"):
            raise UnsupportedAudioError("AP2 PTP is not implemented")
        if "streams" not in fields:
            if self.configured:
                raise ValueError("Session already configured")
            timing = fields.get("timingPort", 0)
            if type(timing) is not int or not 0 <= timing <= 65535:
                raise ValueError("Invalid timing port")
            with self.receiver._lock:
                self.receiver.client_timing = (
                    timing if fields.get("timingProtocol", "NTP") == "NTP" else 0
                )
            return {
                "eventPort": self.events.port,
                "timingPort": self.receiver.ports[1],
                "timingProtocol": fields.get("timingProtocol", "NTP"),
            }
        streams = fields["streams"]
        if not isinstance(streams, list) or len(streams) != 1 or self.configured:
            raise UnsupportedAudioError("Only one realtime stream is supported")
        stream = streams[0]
        if (
            not isinstance(stream, dict)
            or type(stream.get("type")) is not int
            or stream["type"] != 96
        ):
            raise UnsupportedAudioError("Buffered AP2 streams are not implemented")
        fmt = stream.get("audioFormat")
        if type(fmt) is not int or fmt not in FORMATS:
            raise UnsupportedAudioError("Unsupported AP2 audio format")
        codec, rate, channels = FORMATS[fmt]
        if type(stream.get("ct")) is not int or stream["ct"] != codec:
            raise ValueError("Inconsistent compression type")
        samples, control = stream.get("spf", 352), stream.get("controlPort", 0)
        if (
            type(samples) is not int
            or not 1 <= samples <= 4096
            or type(control) is not int
            or not 0 <= control <= 65535
        ):
            raise ValueError("Invalid stream parameters")
        key, iv = stream.get("shk"), stream.get("shiv")
        if not isinstance(key, bytes) or len(key) != 32 or iv is not None:
            raise UnsupportedAudioError("AP2 realtime requires a 32-byte AEAD key")
        sdp = (
            f"a=rtpmap:96 L16/{rate}/{channels}"
            if codec == 1
            else f"a=rtpmap:96 AppleLossless\na=fmtp:96 {samples} 0 16 40 10 14 2 255 0 0 {rate}"
        )
        decoder = AudioDecoder(sdp)
        decoder.frame_samples = samples
        with self.receiver._lock:
            self.receiver.decoder = decoder
            self.receiver.aead_key = key
            self.receiver.client_control = control
        self.configured = True
        return {
            "streams": [
                {
                    "type": 96,
                    "dataPort": self.receiver.ports[0],
                    "controlPort": self.receiver.ports[1],
                    "streamID": self.stream_id,
                    "audioBufferSize": 1048576,
                }
            ]
        }

    def close(self):
        self.events.close()
        self.receiver.close()
