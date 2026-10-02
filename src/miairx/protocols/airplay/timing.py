"""Bounded RAOP NTP measurements; not a speaker-output synchronization clock."""

import struct
import time


def ntp_bytes(seconds):
    value = int((seconds + 2208988800) * 2**32) & (2**64 - 1)
    return value.to_bytes(8, "big")


def ntp_delta(left, right):
    delta = (int.from_bytes(left, "big") - int.from_bytes(right, "big")) & (2**64 - 1)
    if delta >= 2**63:
        delta -= 2**64
    return delta / 2**32


class TimingClock:
    def __init__(self):
        self._wall = time.time()
        self._mono = time.monotonic()
        self._pending = None
        self._next_probe = 0
        self._sequence = 0
        self.samples = 0
        self.offset = None
        self.rtt = None
        self._sample_at = None
        self.sync_latency = None
        self._sync_anchor = None
        self.rate_ratio = 1.0

    def now(self):
        # Wall-clock corrections must not change an in-flight measurement.
        return ntp_bytes(self._wall + time.monotonic() - self._mono)

    def probe(self):
        now = time.monotonic()
        if now < self._next_probe:
            return None
        self._next_probe = now + 1
        stamp = self.now()
        self._pending = (stamp, now)
        packet = struct.pack(">BBH", 0x80, 0xD2, self._sequence) + b"\0" * 20 + stamp
        self._sequence = (self._sequence + 1) & 65535
        return packet

    def accept(self, packet):
        if len(packet) != 32 or not self._pending:
            return False
        origin, sent = self._pending
        if packet[8:16] != origin:
            return False
        self._pending = None  # Replies cannot be replayed.
        elapsed = time.monotonic() - sent
        processing = ntp_delta(packet[24:32], packet[16:24])
        rtt = elapsed - processing
        if not 0 <= elapsed <= 1 or not 0 <= processing <= elapsed or rtt > 0.2:
            return False
        offset = (ntp_delta(packet[16:24], origin) + ntp_delta(packet[24:32], self.now())) / 2
        if abs(offset) > 86400:
            return False
        # Prefer low-delay samples; age out an old estimate instead of freezing it.
        if self.rtt is None or rtt <= self.rtt + 0.002 or not self.fresh:
            self.offset, self.rtt = offset, rtt
            self._sample_at = time.monotonic()
        self.samples += 1
        return True

    @property
    def fresh(self):
        return self._sample_at is not None and time.monotonic() - self._sample_at <= 10

    def sync(self, packet, sample_rate):
        if len(packet) != 20 or not self.fresh:
            return False
        before = int.from_bytes(packet[4:8], "big")
        stamp = int.from_bytes(packet[16:20], "big")
        latency = ((stamp - before) & 0xFFFFFFFF) / sample_rate
        remote_age = ntp_delta(self.now(), packet[8:16]) + self.offset
        if latency > 10 or abs(remote_age) > 2:
            return False
        self.sync_latency = latency
        if self._sync_anchor:
            old_stamp, old_time = self._sync_anchor
            elapsed = ntp_delta(packet[8:16], old_time)
            frames = (stamp - old_stamp) & 0xFFFFFFFF
            if 0.2 <= elapsed <= 30 and frames < 2**31:
                ratio = frames / elapsed / sample_rate
                if 0.995 <= ratio <= 1.005:
                    self.rate_ratio = 0.9 * self.rate_ratio + 0.1 * ratio
        self._sync_anchor = (stamp, packet[8:16])
        return True

    def reset_stream(self):
        self.sync_latency = None
        self._sync_anchor = None
        self.rate_ratio = 1.0
