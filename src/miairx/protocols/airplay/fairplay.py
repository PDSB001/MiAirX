"""Bounded, per-connection FairPlay v3 wrapper around the vendored decryptor."""

import sys
import time

from miairx.protocols.airplay.vendor.replies import REPLIES


class FairPlayError(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__("FairPlay request rejected")


class FairPlaySession:
    def __init__(self):
        self.reset()

    def reset(self):
        self._mode = self._keymsg = self._created = None
        self._used = False

    def setup(self, request):
        if (
            len(request) not in (16, 164)
            or request[:4] != b"FPLY"
            or request[5] != 1
            or request[7] != 0
            or int.from_bytes(request[8:12], "big") != len(request) - 12
        ):
            self.reset()
            raise FairPlayError(400)
        if request[4] != 3:
            self.reset()
            raise FairPlayError(415)
        if request[6] == 1 and len(request) == 16:
            self.reset()
            if request[14] > 3:
                raise FairPlayError(400)
            self._mode, self._created = request[14], time.monotonic()
            return REPLIES[self._mode]
        if request[6] == 3 and len(request) == 164:
            if (
                self._mode is None
                or self._keymsg is not None
                or self._used
                or time.monotonic() - self._created > 30
            ):
                self.reset()
                raise FairPlayError(455)
            if request[12] != self._mode:
                self.reset()
                raise FairPlayError(400)
            self._keymsg = bytes(request)
            return b"FPLY\x03\x01\x04\0\0\0\0\x14" + request[144:164]
        self.reset()
        raise FairPlayError(400)

    def decrypt_key(self, encrypted):
        if self._keymsg is None or self._used or time.monotonic() - self._created > 30:
            self.reset()
            raise FairPlayError(455)
        if (
            len(encrypted) != 72
            or encrypted[:8] != b"FPLY\x01\x02\x01\0"
            or int.from_bytes(encrypted[8:12], "big") != 60
            or int.from_bytes(encrypted[32:36], "big") != 16
        ):
            self.reset()
            raise FairPlayError(400)
        # The inherited implementation uses native uint32 arrays. Fail closed
        # on unsupported hosts rather than silently derive an incorrect key.
        if sys.byteorder != "little":
            raise FairPlayError(503)
        from miairx.protocols.airplay.vendor.fairplay3 import Fairplay3

        self._used = True
        try:
            key = Fairplay3().decryptAESKey(self._keymsg, encrypted)
            if len(key) != 16:
                raise ValueError("Invalid key length")
            return key
        except Exception:
            self.reset()
            raise FairPlayError(400) from None
