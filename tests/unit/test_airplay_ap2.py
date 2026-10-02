"""Encrypted HAP/plist/UDP/HTTP AP2 realtime integration, no Apple device needed."""

import asyncio
import plistlib
import socket
import struct

import aiohttp
import pytest
from Crypto.Cipher import ChaCha20_Poly1305
from test_airplay_hap import connect_transient
from test_airplay_receiver import alac_vector

from miairx.protocols.airplay.ap2 import parse_plist
from miairx.protocols.airplay.hap import HAPChannel, derive
from miairx.protocols.airplay.server import AirplayServer


async def exchange(reader, writer, channel, method, path, seq, fields=None):
    body = plistlib.dumps(fields, fmt=plistlib.FMT_BINARY) if fields is not None else b""
    wire = (
        f"{method} {path} RTSP/1.0\r\nCSeq: {seq}\r\nContent-Length: {len(body)}\r\n"
        "Content-Type: application/x-apple-binary-plist\r\n\r\n"
    ).encode() + body
    writer.write(channel.encrypt(wire))
    await writer.drain()
    plain = b""
    while True:
        end = plain.find(b"\r\n\r\n")
        if end >= 0:
            head = plain[:end].decode()
            headers = dict(row.split(": ", 1) for row in head.split("\r\n")[1:] if ": " in row)
            size = int(headers["Content-Length"])
            if len(plain) >= end + 4 + size:
                assert headers["CSeq"] == str(seq)
                return int(head.split()[1]), plain[end + 4 : end + 4 + size]
        chunk = await asyncio.wait_for(reader.read(8192), 3)
        assert chunk, "Control connection unexpectedly closed"
        plain += channel.feed(chunk)


@pytest.mark.asyncio
@pytest.mark.parametrize("codec", ["pcm", "alac"])
async def test_ap2_authenticated_realtime_to_http_and_reconnect(monkeypatch, codec):
    server = AirplayServer("127.0.0.1", "ap2-test")
    monkeypatch.setattr(server._mdns, "start", lambda: None)
    monkeypatch.setattr(server._mdns, "stop", lambda: None)
    await server.start()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    writer = event_writer = None
    key = bytes(range(32))
    if codec == "alac":
        _, packets, expected = alac_vector()
        fmt, compression, spf = 1 << 18, 2, 4096
    else:
        packets = [struct.pack(">20h", *range(20))]
        expected = struct.pack("<20h", *range(20))
        fmt, compression, spf = 1 << 11, 1, 10
    try:
        for _session in range(2):
            reader, writer, channel, shared = await connect_transient(server)
            status, info = await exchange(reader, writer, channel, "GET", "/info", 3)
            assert status == 200 and plistlib.loads(info)["name"] == "ap2-test"
            assert (
                await exchange(
                    reader, writer, channel, "SETUP", "/stream", 4, {"timingProtocol": "PTP"}
                )
            )[0] == 415
            status, initial = await exchange(
                reader, writer, channel, "SETUP", "/stream", 5, {"timingProtocol": "NTP"}
            )
            initial = plistlib.loads(initial)
            assert status == 200 and initial["timingPort"] > 0
            assert (await exchange(reader, writer, channel, "RECORD", "/stream", 6))[0] == 455
            event_reader, event_writer = await asyncio.open_connection(
                "127.0.0.1", initial["eventPort"]
            )
            events = HAPChannel(
                derive(shared, "Events-Salt", "Events-Write-Encryption-Key"),
                derive(shared, "Events-Salt", "Events-Read-Encryption-Key"),
            )
            assert (await exchange(event_reader, event_writer, events, "OPTIONS", "*", 1))[0] == 200
            fields = {
                "streams": [
                    {"type": 96, "audioFormat": fmt, "ct": compression, "spf": spf, "shk": key}
                ]
            }
            buffered = {"streams": [{"type": 103}]}
            assert (await exchange(reader, writer, channel, "SETUP", "/stream", 60, buffered))[
                0
            ] == 415
            bad_key = {"streams": [{**fields["streams"][0], "shk": bytes(16)}]}
            assert (await exchange(reader, writer, channel, "SETUP", "/stream", 61, bad_key))[
                0
            ] == 415
            status, reply = await exchange(reader, writer, channel, "SETUP", "/stream", 7, fields)
            stream = plistlib.loads(reply)["streams"][0]
            assert status == 200 and stream["type"] == 96
            status, feedback = await exchange(reader, writer, channel, "POST", "/feedback", 70)
            assert (
                status == 200
                and plistlib.loads(feedback)["streams"][0]["streamID"] == stream["streamID"]
            )
            assert (await exchange(reader, writer, channel, "RECORD", "/stream", 8))[0] == 200
            for i, payload in enumerate(packets):
                head = struct.pack(">BBHII", 0x80, 96, 100 + i, i * spf, 12345)
                nonce = i.to_bytes(8, "little")
                cipher = ChaCha20_Poly1305.new(key=key, nonce=nonce)
                cipher.update(head[4:12])
                ciphertext, tag = cipher.encrypt_and_digest(payload)
                packet = head + ciphertext + tag + nonce
                invalid = bytearray(packet)
                invalid[-9] ^= 1
                udp.sendto(invalid, ("127.0.0.1", stream["dataPort"]))
                udp.sendto(packet, ("127.0.0.1", stream["dataPort"]))
            async with (
                aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as http,
                http.get(server._audio_server.stream_url) as sound,
            ):
                data = await sound.content.readexactly(44 + len(expected))
                assert data[:4] == b"RIFF" and data[44:] == expected
            assert server._receiver.invalid >= 1
            assert (await exchange(reader, writer, channel, "TEARDOWN", "/stream", 9))[0] == 200
            assert await asyncio.wait_for(reader.read(), 3) == b""
            writer.close()
            await writer.wait_closed()
            event_writer.close()
            await event_writer.wait_closed()
            writer = event_writer = None
    finally:
        udp.close()
        for connection in (writer, event_writer):
            if connection:
                connection.close()
                await connection.wait_closed()
        await server.stop()


@pytest.mark.parametrize("body", [b"", b"bplist00", plistlib.dumps([], fmt=plistlib.FMT_BINARY)])
def test_invalid_setup_plist(body):
    with pytest.raises(ValueError):
        parse_plist(body)


@pytest.mark.asyncio
async def test_plaintext_ap2_setup_is_forbidden(monkeypatch):
    server = AirplayServer("127.0.0.1", "ap2-test")
    monkeypatch.setattr(server._mdns, "start", lambda: None)
    monkeypatch.setattr(server._mdns, "stop", lambda: None)
    await server.start()
    writer = None
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.rtsp_port)
        body = plistlib.dumps({"timingProtocol": "NTP"}, fmt=plistlib.FMT_BINARY)
        writer.write(
            (f"SETUP /stream RTSP/1.0\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body
        )
        await writer.drain()
        answer = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 3)
        assert answer.startswith(b"RTSP/1.0 403 ") and server._receiver is None
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
        await server.stop()
