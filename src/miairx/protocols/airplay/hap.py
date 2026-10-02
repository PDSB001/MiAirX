"""AirPlay transient HAP pairing and authenticated control framing.

Independent protocol implementation. No persistent pairings, PIN UI, or
trusted-device authorization: transient pairing uses the protocol PIN 3939.
"""

import hashlib
import hmac
import secrets
import time

from Crypto.Cipher import ChaCha20_Poly1305
from Crypto.Hash import SHA512
from Crypto.Protocol.KDF import HKDF

# RFC 5054 Appendix A, 3072-bit SRP group (generator 5).
N = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA6"
    "3B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F2411"
    "7C4B1FE649286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D670C354E4ABC9804F1746C08"
    "CA18217C32905E462E36CE3BE39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA051015728E5A8AAAC42DAD33170D"
    "04507A33A85521ABDF1CBA64ECFB850458DBEF0A8AEA71575D060C7DB3970F85A6E1E4C7"
    "ABF5AE8CDB0933D71E8C94E04A25619DCEE3D2261AD2EE6BF12FFA06D98A0864D8760273"
    "3EC86A64521F2B18177B200CBBE117577A615D6C770988C0BAD946E208E24FA074E5AB31"
    "43DB5BFCE0FD108E4B82D120A93AD2CAFFFFFFFFFFFFFFFF",
    16,
)
G = 5


def number(value, padded=False):
    return value.to_bytes(384 if padded else max(1, (value.bit_length() + 7) // 8), "big")


def digest(*parts):
    return hashlib.sha512(b"".join(parts)).digest()


def derive(secret, salt, info):
    return HKDF(secret, 32, salt.encode(), SHA512, context=info.encode())


def read_tlv(data):
    if len(data) > 4096:
        raise ValueError("HAP TLV too large")
    result, offset, previous, previous_size = {}, 0, None, 0
    while offset < len(data):
        if offset + 2 > len(data):
            raise ValueError("Truncated HAP TLV")
        tag, size = data[offset : offset + 2]
        offset += 2
        if offset + size > len(data):
            raise ValueError("Truncated HAP TLV value")
        if tag in result and (previous != tag or previous_size != 255):
            raise ValueError("Duplicate HAP TLV")
        result[tag] = result.get(tag, b"") + data[offset : offset + size]
        offset += size
        previous, previous_size = tag, size
    return result


def write_tlv(fields):
    result = bytearray()
    for tag, value in fields.items():
        for offset in range(0, max(1, len(value)), 255):
            chunk = value[offset : offset + 255]
            result.extend(bytes([tag, len(chunk)]) + chunk)
    return bytes(result)


class HAPChannelError(ValueError):
    pass


class HAPChannel:
    def __init__(self, input_key, output_key):
        self.input_key, self.output_key = input_key, output_key
        self._incoming = bytearray()
        self._read_counter = self._write_counter = 0
        self._failed = False

    @staticmethod
    def _cipher(key, counter):
        if counter >= 2**64:
            raise HAPChannelError("HAP counter exhausted")
        return ChaCha20_Poly1305.new(key=key, nonce=b"\0" * 4 + counter.to_bytes(8, "little"))

    def encrypt(self, data):
        if self._failed:
            raise HAPChannelError("HAP channel failed")
        output = bytearray()
        for offset in range(0, len(data), 1024):
            block = data[offset : offset + 1024]
            length = len(block).to_bytes(2, "little")
            cipher = self._cipher(self.output_key, self._write_counter)
            cipher.update(length)
            encrypted, tag = cipher.encrypt_and_digest(block)
            output.extend(length + encrypted + tag)
            self._write_counter += 1
        return bytes(output)

    def feed(self, data):
        if self._failed:
            raise HAPChannelError("HAP channel failed")
        self._incoming.extend(data)
        output = bytearray()
        try:
            while len(self._incoming) >= 2:
                length = bytes(self._incoming[:2])
                size = int.from_bytes(length, "little")
                if not 1 <= size <= 1024:
                    raise HAPChannelError("Invalid HAP frame size")
                if len(self._incoming) < size + 18:
                    break
                cipher = self._cipher(self.input_key, self._read_counter)
                cipher.update(length)
                output.extend(
                    cipher.decrypt_and_verify(
                        bytes(self._incoming[2 : size + 2]),
                        bytes(self._incoming[size + 2 : size + 18]),
                    )
                )
                del self._incoming[: size + 18]
                self._read_counter += 1
            return bytes(output)
        except ValueError:
            self._failed = True
            self._incoming.clear()
            raise HAPChannelError("HAP authentication failed") from None


class TransientPairing:
    def __init__(self):
        self.shared = self.channel = self._pending = None
        self.attempts = 0

    def reset(self):
        self.shared = self.channel = self._pending = None

    def setup(self, body):
        fields = read_tlv(body)
        state = fields.get(6)
        if state == b"\1":
            self.reset()
            self.attempts += 1
            if self.attempts > 3:
                return write_tlv({6: b"\2", 7: b"\5"})
            if fields.get(0) != b"\0" or fields.get(19) != b"\x10":
                return write_tlv({6: b"\2", 7: b"\6"})
            salt = secrets.token_bytes(16)
            private = secrets.randbits(512) | (1 << 511)
            x = int.from_bytes(digest(salt, digest(b"Pair-Setup:3939")), "big")
            verifier = pow(G, x, N)
            multiplier = int.from_bytes(digest(number(N), number(G, True)), "big")
            public = (multiplier * verifier + pow(G, private, N)) % N
            self._pending = salt, private, verifier, public, time.monotonic()
            return write_tlv({6: b"\2", 2: salt, 3: number(public, True)})
        pending, self._pending = self._pending, None
        if state != b"\3" or pending is None or time.monotonic() - pending[4] > 30:
            self.reset()
            return write_tlv({6: b"\4", 7: b"\2"})
        salt, private, verifier, public, _ = pending
        client_bytes, proof = fields.get(3, b""), fields.get(4, b"")
        if not 1 <= len(client_bytes) <= 384 or len(proof) != 64:
            return write_tlv({6: b"\4", 7: b"\2"})
        client = int.from_bytes(client_bytes, "big")
        if not 0 < client < N:
            return write_tlv({6: b"\4", 7: b"\2"})
        scramble = int.from_bytes(digest(number(client, True), number(public, True)), "big")
        if not scramble:
            return write_tlv({6: b"\4", 7: b"\2"})
        secret = pow(client * pow(verifier, scramble, N) % N, private, N)
        shared = digest(number(secret))
        xor_hash = bytes(a ^ b for a, b in zip(digest(number(N)), digest(number(G)), strict=True))
        expected = digest(
            xor_hash, digest(b"Pair-Setup"), salt, number(client), number(public), shared
        )
        if not hmac.compare_digest(expected, proof):
            return write_tlv({6: b"\4", 7: b"\2"})
        self.shared = shared
        self.channel = HAPChannel(
            derive(shared, "Control-Salt", "Control-Write-Encryption-Key"),
            derive(shared, "Control-Salt", "Control-Read-Encryption-Key"),
        )
        return write_tlv({6: b"\4", 4: digest(number(client), proof, shared)})
