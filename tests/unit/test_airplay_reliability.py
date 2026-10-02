"""Independent wire fixtures and accelerated soak tests; no Apple sender required."""

import asyncio
import socket
import struct
from types import SimpleNamespace
from unittest.mock import Mock

import aiohttp
import pytest
from test_airplay_receiver import read_response, request

from miairx.protocols.airplay import receiver as receiver_module
from miairx.protocols.airplay import timing as timing_module
from miairx.protocols.airplay.decoder import AudioDecoder
from miairx.protocols.airplay.receiver import Receiver
from miairx.protocols.airplay.server import AirplayServer
from miairx.protocols.airplay.timing import TimingClock


def packet(seq, stamp, value=1, samples=1):
    return struct.pack(">BBHII", 0x80, 96, seq & 65535, stamp & 0xFFFFFFFF, 0) + (
        struct.pack(">hh", value, value) * samples
    )


@pytest.fixture
def virtual_time(monkeypatch):
    clock = SimpleNamespace(value=1000.0)
    fake = SimpleNamespace(monotonic=lambda: clock.value, time=lambda: 1700000000 + clock.value)
    monkeypatch.setattr(receiver_module, "time", fake)
    monkeypatch.setattr(timing_module, "time", fake)
    return clock


def new_receiver(write=None):
    return Receiver(
        "127.0.0.1",
        AudioDecoder("a=rtpmap:96 L16/44100/2"),
        None,
        None,
        (0, 0),
        write or Mock(),
        Mock(),
    )


def test_timing_offset_replay_and_expiry(virtual_time):
    clock = TimingClock()
    probe = clock.probe()
    assert len(probe) == 32 and probe[1] == 0xD2
    assert clock.probe() is None

    # Independent sender clock is 250 ms ahead; 10 ms one-way delay.
    def stamp(seconds):
        seconds += 2208988800
        return struct.pack(">II", int(seconds), int((seconds % 1) * 2**32))

    origin = probe[24:32]
    wall = 1700001000.0
    reply = b"\x80\xd3\0\0" + b"\0" * 4 + origin + stamp(wall + 0.26) * 2
    virtual_time.value += 0.02
    assert clock.accept(reply)
    assert clock.offset == pytest.approx(0.25, abs=1e-6)
    assert clock.rtt == pytest.approx(0.02, abs=1e-6)
    assert not clock.accept(reply)
    sync = b"\x80\xd4\0\4" + struct.pack(">I", 100) + stamp(wall + 0.27) + struct.pack(">I", 4510)
    assert clock.sync(sync, 44100)
    assert clock.sync_latency == pytest.approx(0.1)
    virtual_time.value += 11
    assert not clock.fresh
    assert not clock.sync(sync, 44100)


@pytest.mark.parametrize("fault", ["origin", "delay", "processing", "short"])
def test_untrusted_timing_samples_do_not_change_clock(virtual_time, fault):
    clock = TimingClock()
    probe = clock.probe()
    stamp = probe[24:32]
    reply = b"\x80\xd3\0\0" + b"\0" * 4 + stamp * 3
    if fault == "origin":
        reply = reply[:8] + b"12345678" + reply[16:]
    elif fault == "short":
        reply = reply[:-1]
    elif fault == "processing":
        reply = reply[:24] + (int.from_bytes(stamp, "big") + 2**32).to_bytes(8, "big")
    virtual_time.value += 0.5 if fault == "delay" else 0.02
    assert not clock.accept(reply)
    assert clock.samples == 0 and clock.offset is None


def test_pacing_bursts_and_flush_timestamp_rollover(virtual_time):
    written = []
    receiver = new_receiver(written.append)
    receiver._started = receiver._pace = True
    receiver._expected = 1
    try:
        receiver._insert(packet(1, 0xFFFFFF00, 1))
        receiver._insert(packet(2, 0xFFFFFF00 + 441, 2))
        receiver._drain()
        assert written == [struct.pack("<hh", 1, 1)]
        virtual_time.value += 0.011
        receiver._drain()
        assert written[-1] == struct.pack("<hh", 2, 2)
        receiver.flush(10, 1000)
        receiver._insert(packet(10, 999, 3))
        receiver._insert(packet(10, 1000, 4))
        receiver._drain()
        assert written[-1] == struct.pack("<hh", 4, 4)
        assert receiver.discontinuities == 0
    finally:
        receiver.close()


def test_sync_rate_correction_is_bounded_and_reset_on_flush(virtual_time):
    clock = TimingClock()
    clock.offset, clock.rtt, clock._sample_at = 0, 0.01, virtual_time.value

    def sync(stamp):
        return (
            b"\x80\xd4\0\4"
            + struct.pack(">I", (stamp - 4410) & 0xFFFFFFFF)
            + clock.now()
            + struct.pack(">I", stamp)
        )

    assert clock.sync(sync(4410), 44100)
    virtual_time.value += 1
    assert clock.sync(sync(48554), 44100)
    assert clock.rate_ratio == pytest.approx(1.0001, abs=1e-6)
    virtual_time.value += 1
    assert clock.sync(sync(136754), 44100)
    assert clock.rate_ratio == pytest.approx(1.0001, abs=1e-6)
    clock.reset_stream()
    assert clock.rate_ratio == 1 and clock.sync_latency is None


def test_timestamp_floor_tracks_playback_across_long_session_wrap(virtual_time):
    receiver = new_receiver()
    receiver._started = True
    receiver._expected, receiver._timestamp_floor = 1, 0
    try:
        # A long-running stream must not remain tied to RECORD's original
        # timestamp, which becomes ambiguous after half the 32-bit range.
        for index, stamp in enumerate([0, 2**30, 2**31 - 1, 3 * 2**30, 0xFFFFFFFF, 100]):
            receiver._insert(packet(index + 1, stamp))
            receiver._drain()
        assert receiver.decoded == 6
        assert receiver._timestamp_floor == 100
    finally:
        receiver.close()


def test_retry_budget_recovers_lost_first_request(virtual_time):
    receiver = new_receiver()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.bind(("127.0.0.1", 0))
    sender.settimeout(0.2)
    receiver.client_control = sender.getsockname()[1]
    receiver._started, receiver._expected = True, 10
    try:
        receiver._insert(packet(11, 352))
        receiver._drain()
        sender.recv(64)  # Simulate a lost first request.
        virtual_time.value += 0.03
        receiver._drain()
        retry = sender.recv(64)
        assert struct.unpack(">BBHHH", retry)[3:] == (10, 1)
        receiver._control(b"\x80\xd6\0\0" + packet(10, 0), sender.getsockname())
        receiver._drain()
        assert receiver.decoded == 2 and receiver.lost == 0
        assert receiver.retransmit_requests == 2
        receiver.flush(20)
        receiver._insert(packet(21, 704))
        for _ in range(20):
            receiver._drain()
            virtual_time.value += 0.01
        assert receiver.retransmit_requests <= 5
        assert receiver.lost == 1
    finally:
        receiver.close()
        sender.close()


def test_one_hour_virtual_soak_bounded_buffers_and_rollover(virtual_time):
    written = 0

    def consume(data):
        nonlocal written
        assert len(data) == 1408
        written += 1

    receiver = new_receiver(consume)
    receiver._started = receiver._pace = True
    receiver._expected = 65530
    frames = int(3600 * 44100 / 352)
    try:
        for index in range(frames):
            virtual_time.value = 1000 + index * 352 / 44100 + 1e-7
            receiver._insert(packet(65530 + index, 0xFFFFF000 + index * 352, samples=352))
            receiver._drain()
            assert len(receiver._packets) <= 1
        assert written == frames
        assert receiver.lost == receiver.invalid == receiver.discontinuities == 0
    finally:
        receiver.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("abrupt", [False, True])
async def test_repeated_switch_flush_and_reconnect(monkeypatch, abrupt):
    server = AirplayServer("127.0.0.1", "soak")
    monkeypatch.setattr(server._mdns, "start", lambda: None)
    monkeypatch.setattr(server._mdns, "stop", lambda: None)
    await server.start()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    writer = None
    try:
        for session in range(8):
            reader, writer = await asyncio.open_connection("127.0.0.1", server.rtsp_port)
            writer.write(request("ANNOUNCE", 1, b"v=0\r\na=rtpmap:96 L16/44100/2\r\n"))
            await writer.drain()
            assert (await read_response(reader))[0] == 200
            writer.write(request("SETUP", 2, headers={"Transport": "RTP/AVP/UDP;unicast"}))
            await writer.drain()
            status, headers, _ = await read_response(reader)
            assert status == 200
            ports = dict(p.split("=", 1) for p in headers["Transport"].split(";") if "=" in p)
            writer.write(request("RECORD", 3, headers={"RTP-Info": "seq=100;rtptime=0"}))
            await writer.drain()
            assert (await read_response(reader))[0] == 200
            udp.sendto(packet(100, 0, session), ("127.0.0.1", int(ports["server_port"])))
            async with (
                aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as http,
                http.get(server._audio_server.stream_url) as stream,
            ):
                assert (await stream.content.readexactly(48))[44:] == struct.pack(
                    "<hh", session, session
                )
                writer.write(request("FLUSH", 4, headers={"RTP-Info": "seq=101;rtptime=44100"}))
                await writer.drain()
                assert (await read_response(reader))[0] == 200
                udp.sendto(packet(101, 0, -1), ("127.0.0.1", int(ports["server_port"])))
                udp.sendto(
                    packet(101, 44100, session + 1), ("127.0.0.1", int(ports["server_port"]))
                )
                assert await stream.content.readexactly(4) == struct.pack(
                    "<hh", session + 1, session + 1
                )
            if not abrupt:
                writer.write(request("TEARDOWN", 5))
                await writer.drain()
                assert (await read_response(reader))[0] == 200
            writer.close()
            await writer.wait_closed()
            await asyncio.wait_for(reader.read(), 3)
            for _ in range(100):
                if server._receiver is None and not server._session_lock.locked():
                    break
                await asyncio.sleep(0.01)
            assert server._receiver is None and not server._session_lock.locked()
            assert server.runtime_status()["state"] == "idle"
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
        udp.close()
        await server.stop()
