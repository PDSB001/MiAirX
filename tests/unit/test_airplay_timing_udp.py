import asyncio
import socket
import struct
import time

import pytest
from test_airplay_reliability import new_receiver, packet

pytest_plugins = ["test_airplay_reliability"]


@pytest.mark.asyncio
async def test_active_timing_udp_probe_and_sync():
    receiver = new_receiver()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.bind(("127.0.0.1", 0))
    sender.settimeout(2)
    receiver.client_timing = receiver.client_control = sender.getsockname()[1]
    receiver.listen()
    try:
        probe, destination = await asyncio.to_thread(sender.recvfrom, 64)
        assert len(probe) == 32 and probe[1] == 0xD2

        def ntp():
            value = time.time() + 2208988800
            return struct.pack(">II", int(value), int(value % 1 * 2**32))

        reply = b"\x80\xd3" + probe[2:4] + b"\0" * 4 + probe[24:32] + ntp() + ntp()
        sender.sendto(reply, destination)
        for _ in range(100):
            if receiver.clock.samples:
                break
            await asyncio.sleep(0.01)
        assert receiver.clock.samples == 1 and receiver.clock.fresh
        assert abs(receiver.clock.offset) < 0.1
        sync = b"\x80\xd4\0\4" + struct.pack(">I", 0) + ntp() + struct.pack(">I", 11025)
        sender.sendto(sync, destination)
        for _ in range(100):
            if receiver.clock.sync_latency is not None:
                break
            await asyncio.sleep(0.01)
        assert receiver.clock.sync_latency == pytest.approx(0.25)
        sender.sendto(b"\x80\xd2\0\1" + b"\0" * 20 + ntp(), destination)
        response, _ = await asyncio.to_thread(sender.recvfrom, 64)
        assert response[1] == 0xD3
    finally:
        receiver.close()
        sender.close()


def test_outage_recovers_outside_jitter_window(virtual_time):
    written = []
    receiver = new_receiver(written.append)
    receiver._started = True
    receiver._expected = 100
    try:
        receiver._insert(packet(100, 0))
        receiver._drain()
        receiver._insert(packet(700, 44100))
        assert receiver.invalid == 1
        virtual_time.value += 0.3
        receiver._insert(packet(700, 44100))
        receiver._drain()
        assert receiver.decoded == 2
        assert receiver.lost == 599 and receiver.discontinuities == 1
        assert len(written) == 2 and len(receiver._packets) == 0
    finally:
        receiver.close()


def test_full_window_accepts_missing_head_retransmission():
    receiver = new_receiver()
    receiver._started = True
    receiver._expected = 100
    try:
        for seq in range(101, 613):
            receiver._insert(packet(seq, seq))
        assert len(receiver._packets) == 512
        receiver._insert(packet(100, 100))
        assert len(receiver._packets) == 512
        receiver._drain()
        assert receiver.decoded == 512
    finally:
        receiver.close()


def test_udp_send_failure_does_not_kill_audio_recovery(virtual_time):
    receiver = new_receiver()
    receiver._started, receiver._expected, receiver.client_control = True, 100, 1234
    receiver.control_socket.close()
    try:
        receiver._insert(packet(101, 352))
        receiver._drain()
        virtual_time.value += 0.11
        receiver._drain()
        receiver._drain()
        assert receiver.lost == 1 and receiver.decoded == 1
    finally:
        receiver.close()
