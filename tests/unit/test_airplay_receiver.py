"""Independent sender-side tests: real sockets and cryptographic round trips.

No requests or implementation code are imported from competitor projects.
"""

import asyncio
import base64
import socket
import struct
from unittest.mock import Mock

import aiohttp
import av
import pytest
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.PublicKey import RSA

from miairx.protocols.airplay.audio import AudioStreamServer
from miairx.protocols.airplay.crypto import AIRPORT_PRIVATE_KEY, AirplayCrypto
from miairx.protocols.airplay.decoder import AudioDecoder, UnsupportedAudioError
from miairx.protocols.airplay.receiver import Receiver, rtp_payload
from miairx.protocols.airplay.rtsp import MAX_BODY, extract_request
from miairx.protocols.airplay.server import AirplayServer


def request(method, seq, body=b"", headers=None, path="rtsp://localhost/session"):
    fields = {"CSeq": str(seq), "Content-Length": str(len(body)), **(headers or {})}
    head = f"{method} {path} RTSP/1.0\r\n"
    return (head + "".join(f"{k}: {v}\r\n" for k, v in fields.items()) + "\r\n").encode(
        "ascii"
    ) + body


def test_binary_body_framing_and_pipeline():
    body = b"\xff\0\r\n\r\nvolume: secret"
    first = request("POST", 1, body, path="/fp-setup")
    second = request("OPTIONS", 2)
    for split in range(len(first)):
        parsed, remaining = extract_request(first[:split])
        assert parsed is None and remaining == first[:split]
    parsed, remaining = extract_request(first + second)
    assert parsed.body == body
    assert parsed.headers["cseq"] == "1"
    assert extract_request(remaining)[0].method == "OPTIONS"


@pytest.mark.parametrize(
    "headers",
    [
        f"Content-Length: {MAX_BODY + 1}",
        "Content-Length: -1",
        "Content-Length: 0\r\ncontent-length: 1",
    ],
)
def test_invalid_framing_is_rejected(headers):
    with pytest.raises(ValueError):
        extract_request(f"POST /x RTSP/1.0\r\n{headers}\r\n\r\n".encode())


def test_apple_challenge_signature_with_public_key():
    challenge = bytes(range(16))
    answer = AirplayCrypto.apple_response(
        base64.b64encode(challenge).decode(), "192.168.1.9", "02:11:22:33:44:55"
    )
    key = RSA.import_key(AIRPORT_PRIVATE_KEY).public_key()
    signature = base64.b64decode(answer + "=" * (-len(answer) % 4))
    recovered = pow(int.from_bytes(signature, "big"), key.e, key.n).to_bytes(256, "big")
    expected = (challenge + socket.inet_aton("192.168.1.9") + bytes.fromhex("021122334455")).ljust(
        32, b"\0"
    )
    assert recovered.startswith(b"\0\1\xff")
    assert recovered[-33:] == b"\0" + expected


def test_rsa_oaep_and_partial_aes_block():
    key, iv = bytes(range(16)), bytes(range(16, 32))
    encrypted_key = PKCS1_OAEP.new(RSA.import_key(AIRPORT_PRIVATE_KEY).public_key()).encrypt(key)
    assert AirplayCrypto.decrypt_rsa_aes_key(base64.b64encode(encrypted_key).decode()) == key
    original = bytes(range(37))
    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(original[:32]) + original[32:]
    assert AirplayCrypto.decrypt_aes_cbc(ciphertext, key, iv) == original


def alac_vector():
    encoder = av.CodecContext.create("alac", "w")
    encoder.sample_rate = 44100
    encoder.layout = "stereo"
    encoder.format = "s16p"
    encoder.open()
    params = struct.unpack(">IBBBBBBHIII", encoder.extradata[-24:])
    sdp = "a=rtpmap:96 AppleLossless\r\na=fmtp:96 " + " ".join(map(str, params))
    frame = av.AudioFrame(format="s16p", layout="stereo", samples=4096)
    frame.sample_rate = 44100
    left = struct.pack("<4096h", *(i % 1000 for i in range(4096)))
    right = struct.pack("<4096h", *(-i % 1000 for i in range(4096)))
    frame.planes[0].update(left)
    frame.planes[1].update(right)
    packets = encoder.encode(frame) + encoder.encode(None)
    expected = b"".join(left[i : i + 2] + right[i : i + 2] for i in range(0, len(left), 2))
    return sdp, [bytes(p) for p in packets], expected


def test_alac_decode_uses_real_encoder_and_no_plane_padding():
    sdp, packets, expected = alac_vector()
    decoder = AudioDecoder(sdp)
    decoded = b"".join(decoder.decode(p) for p in packets)
    assert decoded == expected


def test_unsupported_codec_rejected():
    with pytest.raises(UnsupportedAudioError):
        AudioDecoder("a=rtpmap:96 AAC/44100/2")


def test_rtp_extensions_and_padding():
    packet = (
        struct.pack(">BBHII", 0xB1, 96, 65535, 10, 0)
        + b"\0" * 4
        + b"\0\0\0\1"
        + b"ext!"
        + b"pcm!"
        + b"\0\0\0\4"
    )
    assert rtp_payload(packet) == (96, 65535, 10, b"pcm!")
    with pytest.raises(ValueError):
        rtp_payload(b"\x80\x60")


def test_ordering_retransmission_flush_and_rollover():
    decoder = AudioDecoder("a=rtpmap:96 L16/44100/2")
    written, ready = [], Mock()
    receiver = Receiver("127.0.0.1", decoder, None, None, (0, 0), written.append, ready)
    control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    control.bind(("127.0.0.1", 0))
    control.settimeout(1)
    receiver.client_control = control.getsockname()[1]
    receiver._started, receiver._expected = True, 65535

    def packet(seq, value):
        return struct.pack(">BBHII", 0x80, 96, seq, 0, 0) + struct.pack(">hh", value, value)

    try:
        receiver._insert(packet(0, 2))
        receiver._drain()
        resend = control.recv(100)
        assert struct.unpack(">BBHHH", resend)[3:] == (65535, 1)
        receiver._control(b"\x80\xd6\0\0" + packet(65535, 1), ("127.0.0.1", 1))
        receiver._drain()
        assert written == [struct.pack("<hh", 1, 1), struct.pack("<hh", 2, 2)]
        assert ready.call_count == 1
        receiver._insert(packet(0, 2))
        receiver._drain()
        assert len(written) == 2
        receiver.flush(10)
        receiver._insert(packet(10, 3))
        receiver._drain()
        assert written[-1] == struct.pack("<hh", 3, 3)
    finally:
        control.close()
        receiver.close()


def test_timing_reply_echoes_origin():
    receiver = Receiver(
        "127.0.0.1", AudioDecoder("a=rtpmap:96 L16/44100/2"), None, None, (0, 0), Mock(), Mock()
    )
    timing = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    timing.bind(("127.0.0.1", 0))
    timing.settimeout(1)
    try:
        original = b"12345678"
        receiver._control(b"\x80\xd2\0\1" + b"\0" * 20 + original, timing.getsockname())
        reply = timing.recv(64)
        assert len(reply) == 32 and reply[1] == 0xD3 and reply[8:16] == original
    finally:
        receiver.close()
        timing.close()


async def read_response(reader):
    head = (await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 3)).decode("ascii")
    fields = dict(line.split(": ", 1) for line in head.split("\r\n")[1:] if ": " in line)
    body = await reader.readexactly(int(fields.get("Content-Length", "0")))
    return int(head.split()[1]), fields, body


@pytest.mark.asyncio
@pytest.mark.parametrize("codec", ["pcm", "alac"])
@pytest.mark.parametrize("encryption", ["rsa", "fairplay"])
async def test_encrypted_udp_to_http_and_second_session(
    monkeypatch, codec, encryption, fairplay_vector
):
    server = AirplayServer("127.0.0.1", "test", rtsp_port=0, audio_port=0)
    monkeypatch.setattr(server._mdns, "start", lambda: None)
    monkeypatch.setattr(server._mdns, "stop", lambda: None)
    played, stopped = Mock(), Mock()
    server.on_play_start, server.on_play_stop = played, stopped
    await server.start()
    key, iv = bytes(range(16)), bytes(range(16, 32))
    if encryption == "fairplay":
        fp_message, fp_encrypted, key = fairplay_vector
    encoded_key = base64.b64encode(
        PKCS1_OAEP.new(RSA.import_key(AIRPORT_PRIVATE_KEY).public_key()).encrypt(key)
    ).decode()
    if encryption == "fairplay":
        encoded_key = base64.b64encode(fp_encrypted).decode()
    if codec == "alac":
        description, packets, expected = alac_vector()
    else:
        description = "a=rtpmap:96 L16/44100/2"
        packets = [struct.pack(">10h", *range(10))]
        expected = struct.pack("<10h", *range(10))
    sdp = (
        f"v=0\r\n{description}\r\n"
        f"a={'fpaeskey' if encryption == 'fairplay' else 'rsaaeskey'}:{encoded_key}\r\n"
        f"a=aesiv:{base64.b64encode(iv).decode()}\r\n"
    ).encode()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for session in range(2):
            reader, writer = await asyncio.open_connection("127.0.0.1", server.rtsp_port)
            if encryption == "fairplay":
                # Every TCP session needs its own completed handshake.
                if session == 1:
                    writer.write(request("ANNOUNCE", 90, sdp))
                    await writer.drain()
                    assert (await read_response(reader))[0] == 455
                first = b"FPLY\x03\x01\x01\0\0\0\0\x04\x02\0\x01\0"
                writer.write(request("POST", 91, first, path="/fp-setup"))
                await writer.drain()
                status, _, reply = await read_response(reader)
                assert status == 200 and len(reply) == 142
                writer.write(request("POST", 92, fp_message, path="/fp-setup"))
                await writer.drain()
                status, _, reply = await read_response(reader)
                assert status == 200 and len(reply) == 32 and reply[-20:] == fp_message[-20:]
            wire = request("OPTIONS", 1) + request("ANNOUNCE", 2, sdp)
            # Split inside the SDP so receiver must wait for the complete body.
            writer.write(wire[:-17])
            await writer.drain()
            assert (await read_response(reader))[0] == 200
            writer.write(wire[-17:])
            await writer.drain()
            status, fields, _ = await read_response(reader)
            assert status == 200 and fields["CSeq"] == "2"
            writer.write(
                request("SETUP", 3, headers={"Transport": "RTP/AVP/UDP;unicast;mode=record"})
            )
            await writer.drain()
            status, fields, _ = await read_response(reader)
            assert status == 200
            ports = dict(p.split("=", 1) for p in fields["Transport"].split(";") if "=" in p)
            writer.write(request("RECORD", 4, headers={"RTP-Info": "seq=100;rtptime=0"}))
            await writer.drain()
            assert (await read_response(reader))[0] == 200
            for i, payload in enumerate(packets):
                size = len(payload) // 16 * 16
                encrypted = AES.new(key, AES.MODE_CBC, iv).encrypt(payload[:size]) + payload[size:]
                udp.sendto(
                    struct.pack(">BBHII", 0x80, 96, 100 + i, i * 4096, 0) + encrypted,
                    ("127.0.0.1", int(ports["server_port"])),
                )
            async with (
                aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as http,
                http.get(server._audio_server.stream_url) as stream,
            ):
                data = await stream.content.readexactly(44 + len(expected))
                assert data[:4] == b"RIFF"
                assert data[44:] == expected
            assert played.call_count == session + 1
            old_url = server._audio_server.stream_url
            writer.write(request("TEARDOWN", 5))
            await writer.drain()
            assert (await read_response(reader))[0] == 200
            await reader.read()
            writer.close()
            await writer.wait_closed()
            async with aiohttp.ClientSession() as http, http.get(old_url) as stream:
                assert stream.status == 404
        assert stopped.call_count == 2
    finally:
        udp.close()
        await server.stop()


@pytest.mark.asyncio
async def test_unsupported_post_returns_specific_error_and_preserves_connection(monkeypatch):
    server = AirplayServer("127.0.0.1", "test")
    monkeypatch.setattr(server._mdns, "start", lambda: None)
    monkeypatch.setattr(server._mdns, "stop", lambda: None)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.rtsp_port)
        writer.write(request("POST", 7, b"\0\xff", path="/fp-setup") + request("OPTIONS", 8))
        await writer.drain()
        status, fields, _ = await read_response(reader)
        assert status == 400 and fields["CSeq"] == "7"
        assert (await read_response(reader))[1]["CSeq"] == "8"
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


def test_wav_header_sizes_fit_uint32():
    head = AudioStreamServer("127.0.0.1")._build_wav_header(0)
    assert len(head) == 44
    assert struct.unpack_from("<I", head, 4)[0] == struct.unpack_from("<I", head, 40)[0] + 36
