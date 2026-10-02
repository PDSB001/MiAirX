"""Per-session UDP receiver for classic RAOP audio and RTCP."""

import logging
import select
import socket
import struct
import threading
import time
from contextlib import suppress

from Crypto.Cipher import ChaCha20_Poly1305

from miairx.protocols.airplay.crypto import AirplayCrypto
from miairx.protocols.airplay.timing import TimingClock

log = logging.getLogger(__name__)


def rtp_payload(packet: bytes) -> tuple[int, int, int, bytes]:
    if len(packet) < 12 or packet[0] >> 6 != 2:
        raise ValueError("Invalid RTP header")
    offset = 12 + 4 * (packet[0] & 15)
    if packet[0] & 16:
        if len(packet) < offset + 4:
            raise ValueError("Invalid RTP extension")
        offset += 4 + 4 * int.from_bytes(packet[offset + 2 : offset + 4], "big")
    end = len(packet)
    if packet[0] & 32:
        padding = packet[-1]
        if padding == 0 or padding > end - offset:
            raise ValueError("Invalid RTP padding")
        end -= padding
    if offset >= end:
        raise ValueError("Empty RTP packet")
    seq, stamp = struct.unpack_from(">HI", packet, 2)
    return packet[1] & 127, seq, stamp, packet[offset:end]


class Receiver:
    """Control and timing share a UDP socket; packet types distinguish them.

    The TCP RTSP and HTTP port numbers are reused for UDP, so existing port
    allocation still gives each speaker a separate pair of predictable ports.
    """

    def __init__(self, peer, decoder, key, iv, ports, write_pcm, on_audio):
        self.peer = peer
        self.decoder = decoder
        self.key, self.iv = key, iv
        self.aead_key = None
        self.write_pcm, self.on_audio = write_pcm, on_audio
        self.audio_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.audio_socket.bind(("0.0.0.0", ports[0]))
            self.control_socket.bind(("0.0.0.0", ports[1]))
        except Exception:
            self.audio_socket.close()
            self.control_socket.close()
            raise
        self.ports = (self.audio_socket.getsockname()[1], self.control_socket.getsockname()[1])
        self.client_control = 0
        self.client_timing = 0
        self.clock = TimingClock()
        self._pace = False
        self._anchor = None
        self._timestamp_floor = None
        self._retry_at = None
        self._retries = 0
        self.retransmit_requests = self.discontinuities = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._packets = {}
        self._expected = None
        self._gap_since = None
        self._resend_seq = 0
        self._notified = False
        self._started = False
        self.received = self.decoded = self.lost = self.invalid = 0
        self.last_audio = time.monotonic()

    def start(self, sequence=None, timestamp=None):
        with self._lock:
            self._expected = sequence
            self._pace = True
            self._anchor = None
            self._timestamp_floor = timestamp
            self._started = True
        self.listen()

    def listen(self):
        """Timing exchanges can arrive after SETUP, before RECORD."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="miairx-raop")
            self._thread.start()

    def flush(self, sequence=None, timestamp=None):
        with self._lock:
            self._packets.clear()
            self._expected = sequence
            self._gap_since = None
            self._retry_at = None
            self._retries = 0
            self._anchor = None
            self._timestamp_floor = timestamp
            self.clock.reset_stream()

    def close(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
        self.audio_socket.close()
        self.control_socket.close()
        log.info(
            "RAOP session ended: packets=%d decoded=%d lost=%d invalid=%d",
            self.received,
            self.decoded,
            self.lost,
            self.invalid,
        )

    def _run(self):
        try:
            while not self._stop.is_set():
                readable, _, _ = select.select(
                    [self.audio_socket, self.control_socket],
                    [],
                    [],
                    0.02,
                )
                for source in readable:
                    packet, addr = source.recvfrom(65535)
                    if addr[0] != self.peer:
                        continue
                    with self._lock:
                        if source is self.control_socket:
                            self._control(packet, addr)
                        else:
                            self._insert(packet)
                with self._lock:
                    if self.client_timing:
                        probe = self.clock.probe()
                        if probe:
                            # A timing send failure must not stop audio reception.
                            with suppress(OSError):
                                self.control_socket.sendto(probe, (self.peer, self.client_timing))
                    self._drain()
        except OSError:
            if not self._stop.is_set():
                log.exception("RAOP UDP receive failed")

    def _control(self, packet, addr):
        if len(packet) < 4 or packet[0] >> 6 != 2:
            return
        kind = packet[1] & 127
        if kind == 86:  # retransmitted RTP is prefixed by a four-byte RTCP header
            self._insert(packet[4:])
        elif kind == 82 and len(packet) >= 32:  # NTP timing request
            received = self.clock.now()
            reply = (
                b"\x80\xd3" + packet[2:4] + b"\0" * 4 + packet[24:32] + received + self.clock.now()
            )
            with suppress(OSError):
                self.control_socket.sendto(reply, addr)
        elif kind == 83 and addr[1] == self.client_timing:
            self.clock.accept(packet)
        elif kind == 84 and addr[1] == self.client_control:
            self.clock.sync(packet, self.decoder.sample_rate)

    def _insert(self, packet):
        if not self._started:
            return
        try:
            kind, seq, stamp, payload = rtp_payload(packet)
            if kind != self.decoder.payload_type:
                raise ValueError("Unnegotiated RTP payload type")
            if self.aead_key is not None:
                # AP2 realtime: fixed RTP header, ciphertext, tag, 8-byte nonce.
                # Authenticate BEFORE accepting the sequence into the jitter buffer.
                if packet[0] != 0x80 or len(payload) < 25:
                    raise ValueError("Unsupported AP2 RTP header")
                cipher = ChaCha20_Poly1305.new(key=self.aead_key, nonce=payload[-8:])
                cipher.update(packet[4:12])
                payload = cipher.decrypt_and_verify(payload[:-24], payload[-24:-8])
            if (
                self._timestamp_floor is not None
                and (stamp - self._timestamp_floor) & 0xFFFFFFFF >= 2**31
            ):
                return  # Stale pre-FLUSH audio, including timestamp rollover.
            if self._expected is None:
                self._expected = seq
            distance = (seq - self._expected) & 65535
            if distance >= 32768:  # old/duplicate packet, including sequence rollover
                return
            if distance > 512 and time.monotonic() - self.last_audio >= 0.25:
                # An authenticated/fresh forward packet after an outage must
                # recover instead of being rejected forever outside the window.
                self.lost += distance
                self.discontinuities += 1
                self._packets.clear()
                self._expected = seq
                self._anchor = self._gap_since = self._retry_at = None
                self._retries = 0
                distance = 0
            if distance > 512:
                self.invalid += 1
                return
            if seq in self._packets:
                return
            if len(self._packets) >= 512:
                if seq != self._expected:
                    self.invalid += 1
                    return
                # Reserve room for the missing head's retransmission.
                farthest = max(self._packets, key=lambda s: (s - self._expected) & 65535)
                del self._packets[farthest]
            self._packets[seq] = (stamp, payload)
            self.received += 1
            self.last_audio = time.monotonic()
        except ValueError:
            self.invalid += 1

    def _drain(self):
        if self._expected is None or not self._packets:
            return
        while self._expected in self._packets:
            stamp, payload = self._packets[self._expected]
            if self._pace:
                now = time.monotonic()
                if self._anchor is None:
                    self._anchor = (stamp, now)
                delta = (stamp - self._anchor[0]) & 0xFFFFFFFF
                if delta >= 2**31:
                    delta -= 2**32
                ratio = self.clock.rate_ratio if self.clock.fresh else 1.0
                due = self._anchor[1] + delta / (self.decoder.sample_rate * ratio)
                if due > now + 1 or due < now - 0.25:
                    # A seek, stalled sender, or clock discontinuity must not
                    # cause seconds of silence or an unbounded catch-up burst.
                    self.discontinuities += 1
                    due = now
                elif due > now:
                    return  # Keep receiving control/UDP while waiting; never sleep under lock.
                # Incremental anchors keep small rate corrections continuous,
                # rather than shifting an hour-old playback timeline at once.
                self._anchor = (stamp, due)
            self._packets.pop(self._expected)
            self._expected = (self._expected + 1) & 65535
            self._gap_since = None
            self._retry_at = None
            self._retries = 0
            try:
                if self.key:
                    payload = AirplayCrypto.decrypt_aes_cbc(payload, self.key, self.iv)
                pcm = self.decoder.decode(payload)
                if pcm:
                    self.write_pcm(pcm)
                    self._timestamp_floor = stamp
                    self.decoded += 1
                    if not self._notified:
                        self._notified = True
                        self.on_audio()
            except Exception as exc:
                self.invalid += 1
                if self.invalid <= 3:
                    log.warning("RAOP audio decode failed (%s)", type(exc).__name__)
        if not self._packets:
            return
        if self._gap_since is None:
            self._gap_since = time.monotonic()
        now = time.monotonic()
        if (
            self.client_control
            and self._retries < 3
            and (self._retry_at is None or now >= self._retry_at)
            and now - self._gap_since < 0.1
        ):
            nearest = min((s - self._expected) & 65535 for s in self._packets)
            request = struct.pack(
                ">BBHHH", 0x80, 0xD5, self._resend_seq, self._expected, min(nearest, 32)
            )
            self._resend_seq = (self._resend_seq + 1) & 65535
            self._retries += 1
            self._retry_at = now + 0.025
            try:
                self.control_socket.sendto(request, (self.peer, self.client_control))
                self.retransmit_requests += 1
            except OSError:
                pass
        if now - self._gap_since >= 0.1:
            nearest = min((s - self._expected) & 65535 for s in self._packets)
            self.lost += nearest
            # Bound concealment to avoid a burst of stale silence after a long gap.
            silence = b"\0" * (self.decoder.frame_samples * self.decoder.channels * 2)
            for _ in range(min(nearest, 8)):
                self.write_pcm(silence)
            self._expected = (self._expected + nearest) & 65535
            self._gap_since = None
            self._retry_at = None
            self._retries = 0
