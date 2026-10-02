"""HAP framing and SRP verified with independent sender-side srptools."""

import asyncio
import hashlib
import json
import shutil
import subprocess
from binascii import unhexlify

import pytest

from miairx.protocols.airplay.hap import (
    HAPChannel,
    HAPChannelError,
    TransientPairing,
    derive,
    read_tlv,
    write_tlv,
)
from miairx.protocols.airplay.server import AirplayServer


def srp_client(fields, password="3939"):
    srp = pytest.importorskip("srptools")
    from srptools import constants

    client = srp.SRPClientSession(
        srp.SRPContext(
            "Pair-Setup",
            password,
            prime=constants.PRIME_3072,
            generator=constants.PRIME_3072_GEN,
            hash_func=hashlib.sha512,
        )
    )
    client.process(fields[3].hex(), fields[2].hex())
    return client


def shared(client):
    return bytes.fromhex(client.key.decode() if isinstance(client.key, bytes) else client.key)


def proof_fields(client):
    return {6: b"\3", 3: unhexlify(client.public), 4: unhexlify(client.key_proof)}


def test_transient_srp_matches_independent_sender():
    receiver = TransientPairing()
    second = read_tlv(receiver.setup(write_tlv({0: b"\0", 6: b"\1", 19: b"\x10"})))
    client = srp_client(second)
    fourth = read_tlv(receiver.setup(write_tlv(proof_fields(client))))
    assert fourth[6] == b"\4" and fourth[4] == unhexlify(client.key_proof_hash)
    assert receiver.shared == shared(client) and receiver.channel is not None
    assert read_tlv(receiver.setup(write_tlv(proof_fields(client))))[7] == b"\2"
    assert receiver.channel is None and receiver.shared is None


def test_bad_proof_expiry_zero_public_and_attempt_limit(monkeypatch):
    receiver = TransientPairing()
    start = write_tlv({0: b"\0", 6: b"\1", 19: b"\x10"})
    now = [100.0]
    monkeypatch.setattr("miairx.protocols.airplay.hap.time.monotonic", lambda: now[0])
    second = read_tlv(receiver.setup(start))
    wrong = srp_client(second, "3940")
    assert read_tlv(receiver.setup(write_tlv(proof_fields(wrong))))[7] == b"\2"
    assert receiver.shared is None and receiver.channel is None
    second = read_tlv(receiver.setup(start))
    client = srp_client(second)
    now[0] += 31
    assert read_tlv(receiver.setup(write_tlv(proof_fields(client))))[7] == b"\2"
    receiver.setup(start)
    assert read_tlv(receiver.setup(write_tlv({6: b"\3", 3: bytes(384), 4: bytes(64)})))[7] == b"\2"
    assert read_tlv(receiver.setup(start))[7] == b"\5"


@pytest.mark.parametrize("size", [0, 1, 254, 255, 256, 384, 4000])
def test_tlv_fragmentation(size):
    data = bytes(i % 256 for i in range(size))
    assert read_tlv(write_tlv({3: data})) == {3: data}


@pytest.mark.parametrize("body", [b"\3", b"\3\2x", b"\6\1\1\6\1\3", bytes(4097)])
def test_bad_tlv_rejected(body):
    with pytest.raises(ValueError):
        read_tlv(body)


def test_hap_frames_fragmentation_counters_tag_and_replay():
    first, second = bytes(range(32)), bytes(range(32, 64))
    sender, receiver = HAPChannel(second, first), HAPChannel(first, second)
    original = bytes(range(256)) * 13
    wire = sender.encrypt(original)
    output = b"".join(receiver.feed(wire[i : i + 1]) for i in range(len(wire)))
    assert output == original
    assert sender.feed(receiver.encrypt(b"reply")) == b"reply"
    with pytest.raises(HAPChannelError):
        receiver.feed(wire)
    with pytest.raises(HAPChannelError):
        receiver.feed(sender.encrypt(b"next"))
    receiver = HAPChannel(first, second)
    corrupt = bytearray(wire)
    corrupt[10] ^= 1
    with pytest.raises(HAPChannelError):
        receiver.feed(corrupt)
    with pytest.raises(HAPChannelError):
        HAPChannel(first, second).feed(b"\1\x04")


def test_hap_aead_with_node_openssl():
    node = shutil.which("node")
    if not node:
        pytest.skip("Optional independent Node/OpenSSL AEAD test")
    script = r"""
    const c = require('node:crypto');
    const input = JSON.parse(require('node:fs').readFileSync(0,'utf8'));
    const key = Buffer.from(input.key,'hex'), data = Buffer.from(input.data,'hex');
    const parts = [];
    for (let offset=0,counter=0n; offset<data.length; offset+=1024,counter++) {
      const block=data.subarray(offset,offset+1024), aad=Buffer.alloc(2), nonce=Buffer.alloc(12);
      aad.writeUInt16LE(block.length); nonce.writeBigUInt64LE(counter,4);
      const cipher=c.createCipheriv('chacha20-poly1305',key,nonce,{authTagLength:16});
      cipher.setAAD(aad);
      parts.push(aad,cipher.update(block),cipher.final(),cipher.getAuthTag());
    }
    console.log(Buffer.concat(parts).toString('hex'));
    """
    key, data = bytes(range(32)), b"independent" * 180
    result = subprocess.run(
        [node, "-e", script],
        input=json.dumps({"key": key.hex(), "data": data.hex()}),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    wire = bytes.fromhex(result.stdout.strip())
    assert HAPChannel(key, key).feed(wire) == data
    assert HAPChannel(key, key).encrypt(data) == wire


async def connect_transient(server, pipeline=None):
    reader, writer = await asyncio.open_connection("127.0.0.1", server.rtsp_port)
    channel = None

    async def post(body, seq):
        header = (
            f"POST /pair-setup RTSP/1.0\r\nCSeq: {seq}\r\nX-Apple-HKP: 4\r\n"
            f"Content-Length: {len(body)}\r\n\r\n"
        ).encode()
        writer.write(header + body + (channel.encrypt(pipeline) if seq == 2 and pipeline else b""))
        await writer.drain()
        wire = (await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 3)).decode()
        assert wire.startswith("RTSP/1.0 200 ")
        fields = dict(row.split(": ", 1) for row in wire.split("\r\n") if ": " in row)
        return read_tlv(await reader.readexactly(int(fields["Content-Length"])))

    try:
        second = await post(write_tlv({0: b"\0", 6: b"\1", 19: b"\x10"}), 1)
        client = srp_client(second)
        secret = shared(client)
        channel = HAPChannel(
            derive(secret, "Control-Salt", "Control-Read-Encryption-Key"),
            derive(secret, "Control-Salt", "Control-Write-Encryption-Key"),
        )
        fourth = await post(write_tlv(proof_fields(client)), 2)
        assert fourth[4] == unhexlify(client.key_proof_hash)
        return reader, writer, channel, secret
    except BaseException:
        writer.close()
        await writer.wait_closed()
        raise


@pytest.mark.asyncio
@pytest.mark.parametrize("pipeline", [False, True])
async def test_real_tcp_plaintext_m4_then_encrypted_options(monkeypatch, pipeline):
    server = AirplayServer("127.0.0.1", "hap-test")
    monkeypatch.setattr(server._mdns, "start", lambda: None)
    monkeypatch.setattr(server._mdns, "stop", lambda: None)
    await server.start()
    writer = None
    try:
        options = b"OPTIONS * RTSP/1.0\r\nCSeq: 3\r\n\r\n"
        reader, writer, channel, _ = await connect_transient(server, options if pipeline else None)
        if not pipeline:
            writer.write(channel.encrypt(options))
            await writer.drain()
        plaintext = b""
        while b"\r\n\r\n" not in plaintext:
            plaintext += channel.feed(await asyncio.wait_for(reader.read(4096), 3))
        assert plaintext.startswith(b"RTSP/1.0 200 ") and b"CSeq: 3\r\n" in plaintext
        corrupted = bytearray(channel.encrypt(b"OPTIONS * RTSP/1.0\r\n\r\n"))
        corrupted[-1] ^= 1
        writer.write(corrupted)
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), 3) == b""
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
        await server.stop()


def test_global_hap_rate_budget_is_bounded():
    server = AirplayServer("127.0.0.1", "hap-test")
    assert all(server._allow_hap("peer") for _ in range(5))
    assert not server._allow_hap("peer")
    for i in range(300):
        server._allow_hap(str(i))
    assert len(server._hap_budget) <= 256
