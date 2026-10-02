"""Independent no-PIN legacy pairing, not HAP or FairPlay key decryption.

This verifies possession of the client's supplied signing key. Without PIN/
stored trust it does NOT authorize a previously trusted user or device.
"""

import hashlib
import time

from Crypto.Cipher import AES
from Crypto.Protocol.DH import import_x25519_public_key, key_agreement
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa


class PairingError(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__("Legacy pairing rejected")


class LegacyPairing:
    def __init__(self, signing_key):
        self.signing_key = signing_key
        self.reset()

    def reset(self):
        self.verified = False
        self._pending = None

    def setup(self, body):
        self.reset()
        if len(body) != 32:
            raise PairingError(400)
        return self.signing_key.public_key().export_key(format="raw")

    def verify(self, body):
        if len(body) != 68 or body[:4] not in (b"\1\0\0\0", b"\0\0\0\0"):
            self.reset()
            raise PairingError(400)
        if body[0] == 1:
            self.reset()
            try:
                peer_exchange = import_x25519_public_key(body[4:36])
                peer_signing = eddsa.import_public_key(body[36:68])
                private = ECC.generate(curve="Curve25519")
                public = private.public_key().export_key(format="raw")
                shared = key_agreement(
                    eph_priv=private, eph_pub=peer_exchange, kdf=lambda secret: secret
                )
                key = hashlib.sha512(b"Pair-Verify-AES-Key" + shared).digest()[:16]
                iv = hashlib.sha512(b"Pair-Verify-AES-IV" + shared).digest()[:16]
                cipher = AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=iv)
                signature = eddsa.new(self.signing_key, "rfc8032").sign(public + body[4:36])
                encrypted = cipher.encrypt(signature)
                # The second signature continues the SAME CTR stream, not a new IV.
                self._pending = (cipher, peer_signing, body[4:36] + public, time.monotonic())
                return public + encrypted
            except ValueError:
                self.reset()
                raise PairingError(400) from None
        pending, self._pending = self._pending, None
        self.verified = False
        if pending is None or time.monotonic() - pending[3] > 30:
            raise PairingError(455)
        cipher, peer_signing, message, _ = pending
        try:
            # CTR uses XOR in either direction; keep PyCryptodome's operation
            # unchanged so its stateful API continues the first 64 bytes.
            eddsa.new(peer_signing, "rfc8032").verify(message, cipher.encrypt(body[4:]))
        except ValueError:
            raise PairingError(403) from None
        self.verified = True
        return b""
