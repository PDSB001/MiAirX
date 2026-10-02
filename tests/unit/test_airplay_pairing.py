"""Sender-side legacy pairing tests, without importing competitor code."""

import asyncio
import hashlib
import json
import shutil
import subprocess

import pytest
from Crypto.Cipher import AES
from Crypto.Protocol.DH import import_x25519_private_key, import_x25519_public_key, key_agreement
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from miairx.protocols.airplay.legacy_pairing import LegacyPairing, PairingError
from miairx.protocols.airplay.rtsp import extract_request, response
from miairx.protocols.airplay.server import AirplayServer


def test_legacy_with_independent_node_openssl_sender():
    node = shutil.which("node")
    if not node:
        pytest.skip("Optional independent Node/OpenSSL interoperability test")
    script = r"""
    const c = require('node:crypto');
    const fs = require('node:fs');
    const input = JSON.parse(fs.readFileSync(0, 'utf8'));
    const raw = key => key.export({type:'spki',format:'der'}).subarray(-32);
    if (!input.reply) {
      const x = c.generateKeyPairSync('x25519');
      const ed = c.generateKeyPairSync('ed25519');
      console.log(JSON.stringify({
        x:x.privateKey.export({type:'pkcs8',format:'der'}).toString('hex'),
        ed:ed.privateKey.export({type:'pkcs8',format:'der'}).toString('hex'),
        start:Buffer.concat([Buffer.from([1,0,0,0]),raw(x.publicKey),raw(ed.publicKey)]).toString('hex')
      }));
    } else {
      const fromPrivate = hex => c.createPrivateKey({
        key:Buffer.from(hex,'hex'),type:'pkcs8',format:'der'});
      const fromPublic = (hex,oid) => c.createPublicKey({
        key:Buffer.concat([Buffer.from('302a300506032b65'+oid+'032100','hex'),Buffer.from(hex,'hex')]),
        type:'spki',format:'der'});
      const reply = Buffer.from(input.reply,'hex');
      const start = Buffer.from(input.start,'hex');
      const shared = c.diffieHellman({privateKey:fromPrivate(input.x),
        publicKey:fromPublic(reply.subarray(0,32).toString('hex'),'6e')});
      const hash = label => c.createHash('sha512').update(label)
        .update(shared).digest().subarray(0,16);
      const stream = c.createDecipheriv('aes-128-ctr',
        hash('Pair-Verify-AES-Key'),hash('Pair-Verify-AES-IV'));
      const signature = stream.update(reply.subarray(32));
      const valid = c.verify(null,Buffer.concat([reply.subarray(0,32),start.subarray(4,36)]),
        fromPublic(input.identity,'70'),signature);
      if (!valid) throw new Error('Receiver signature rejected by OpenSSL');
      const signed = c.sign(null,Buffer.concat([start.subarray(4,36),reply.subarray(0,32)]),
        fromPrivate(input.ed));
      console.log(JSON.stringify({finish:Buffer.concat([Buffer.alloc(4),stream.update(signed)]).toString('hex')}));
    }
    """

    def run(data):
        result = subprocess.run(
            [node, "-e", script],
            input=json.dumps(data),
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        return json.loads(result.stdout)

    client = run({})
    receiver = LegacyPairing(ECC.generate(curve="Ed25519"))
    start = bytes.fromhex(client["start"])
    client["identity"] = receiver.setup(start[36:]).hex()
    client["reply"] = receiver.verify(start).hex()
    finish = bytes.fromhex(run(client)["finish"])
    assert receiver.verify(finish) == b"" and receiver.verified


def sender_start():
    # RFC 7748 Alice private key; no receiver-generated client fixture.
    exchange = import_x25519_private_key(
        bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
    )
    signing = ECC.generate(curve="Ed25519")
    public = exchange.public_key().export_key(format="raw")
    return exchange, signing, b"\1\0\0\0" + public + signing.public_key().export_key(format="raw")


def sender_finish(exchange, signing, start, reply, identity):
    shared = key_agreement(
        eph_priv=exchange, eph_pub=import_x25519_public_key(reply[:32]), kdf=lambda secret: secret
    )
    key = hashlib.sha512(b"Pair-Verify-AES-Key" + shared).digest()[:16]
    iv = hashlib.sha512(b"Pair-Verify-AES-IV" + shared).digest()[:16]
    cipher = AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=iv)
    eddsa.new(eddsa.import_public_key(identity), "rfc8032").verify(
        reply[:32] + start[4:36], cipher.encrypt(reply[32:])
    )
    signed = eddsa.new(signing, "rfc8032").sign(start[4:36] + reply[:32])
    return b"\0\0\0\0" + cipher.encrypt(signed)


def test_legacy_roundtrip_replay_and_tamper():
    receiver = LegacyPairing(ECC.generate(curve="Ed25519"))
    exchange, signing, start = sender_start()
    identity = receiver.setup(start[36:])
    finish = sender_finish(exchange, signing, start, receiver.verify(start), identity)
    assert receiver.verify(finish) == b"" and receiver.verified
    with pytest.raises(PairingError) as error:
        receiver.verify(finish)
    assert error.value.status == 455 and not receiver.verified
    finish = sender_finish(exchange, signing, start, receiver.verify(start), identity)
    with pytest.raises(PairingError) as error:
        receiver.verify(finish[:-1] + bytes([finish[-1] ^ 1]))
    assert error.value.status == 403 and not receiver.verified


def test_legacy_expiry_and_connection_isolation(monkeypatch):
    identity = ECC.generate(curve="Ed25519")
    first, second = LegacyPairing(identity), LegacyPairing(identity)
    exchange, signing, start = sender_start()
    clock = [100.0]
    monkeypatch.setattr("miairx.protocols.airplay.legacy_pairing.time.monotonic", lambda: clock[0])
    finish = sender_finish(
        exchange,
        signing,
        start,
        first.verify(start),
        identity.public_key().export_key(format="raw"),
    )
    with pytest.raises(PairingError) as error:
        second.verify(finish)
    assert error.value.status == 455
    clock[0] += 31
    with pytest.raises(PairingError) as error:
        first.verify(finish)
    assert error.value.status == 455


@pytest.mark.parametrize(
    "body", [b"", bytes(67), bytes(69), b"\2\0\0\0" + bytes(64), b"\1\0\0\0" + bytes(64)]
)
def test_legacy_invalid_requests(body):
    receiver = LegacyPairing(ECC.generate(curve="Ed25519"))
    with pytest.raises(PairingError) as error:
        receiver.verify(body)
    assert error.value.status == 400 and not receiver.verified


def test_response_matches_request_protocol():
    parsed, _ = extract_request(b"POST /feedback HTTP/1.1\r\nContent-Length: 0\r\n\r\n")
    assert response(200, version=parsed.version).startswith(b"HTTP/1.1 200 OK")


@pytest.mark.asyncio
async def test_pairing_over_real_tcp_and_hap_not_misidentified(monkeypatch):
    server = AirplayServer("127.0.0.1", "pairing-test")
    monkeypatch.setattr(server._mdns, "start", lambda: None)
    monkeypatch.setattr(server._mdns, "stop", lambda: None)
    await server.start()
    writer = None
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.rtsp_port)

        async def post(path, body, seq, content_type="application/octet-stream"):
            head = (
                f"POST {path} HTTP/1.1\r\nCSeq: {seq}\r\nContent-Type: {content_type}\r\n"
                f"Content-Length: {len(body)}\r\n\r\n"
            ).encode()
            writer.write(head + body)
            await writer.drain()
            header = (await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 3)).decode()
            assert header.startswith("HTTP/1.1 ") and f"CSeq: {seq}\r\n" in header
            fields = dict(line.split(": ", 1) for line in header.split("\r\n")[1:] if ": " in line)
            data = await reader.readexactly(int(fields["Content-Length"]))
            return int(header.split()[1]), data

        exchange, signing, start = sender_start()
        status, identity = await post("/pair-setup", start[36:], 1)
        assert status == 200 and len(identity) == 32
        status, reply = await post("/pair-verify", start, 2)
        assert status == 200 and len(reply) == 96
        finish = sender_finish(exchange, signing, start, reply, identity)
        assert await post("/pair-verify", finish, 3) == (200, b"")
        assert await post("/pair-verify", finish, 4) == (455, b"")
        assert await post("/pair-setup", bytes(32), 5, "application/pairing+tlv8") == (501, b"")
        assert await post("/pair-setup", b"bad", 6) == (400, b"")
        assert await post("/feedback", b"", 7) == (200, b"")
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
        await server.stop()
