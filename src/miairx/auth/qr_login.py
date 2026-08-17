"""Xiaomi account QR-code login.

Transplanted from the ``miair-next`` project (which in turn follows
``xiaomusic`` / ``songloft-plugin-miot``). The flow produces the same
``userId`` + ``passToken`` pair that ``AuthManager`` already accepts via
``config.cookie``, so no further token exchange (``serviceToken`` etc.) is
required.

Three-step handshake against ``account.xiaomi.com``:

1. ``serviceLogin`` -> ``_sign``, ``qs``, ``callback``
2. ``longPolling/loginUrl`` -> QR image URL, ``loginUrl``, long-poll ``lp``
3. poll ``lp`` until the user scans and confirms -> ``passToken`` + ``userId``

The long-poll endpoint returns 403 when the code expires and a JSON body with
``code != 0`` when it is invalidated; a timeout only means "still waiting".
"""

import asyncio
import base64
import json
import logging
import secrets
import time
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

POLL_TIMEOUT_SECONDS = 25
MAX_POLL_COUNT = 20
SESSION_TTL_SECONDS = 300

STATE_WAITING = "waiting"
STATE_SCANNED = "scanned"
STATE_CONFIRMED = "confirmed"
STATE_EXPIRED = "expired"
STATE_FAILED = "failed"

_TERMINAL_STATES = {STATE_CONFIRMED, STATE_EXPIRED, STATE_FAILED}

_SERVICE_LOGIN_URL = "https://account.xiaomi.com/pass/serviceLogin"
_LOGIN_URL_ENDPOINT = "https://account.xiaomi.com/longPolling/loginUrl"

_JSONP_PREFIX = "&&&START&&&"


def _strip_jsonp_prefix(text: str) -> str:
    """Remove the ``&&&START&&&`` prefix Xiaomi prepends to JSON responses."""
    if _JSONP_PREFIX in text:
        return text[text.index(_JSONP_PREFIX) + len(_JSONP_PREFIX):]
    return text


def _as_str(value) -> str:
    return "" if value is None else str(value)


class QRCodeLogin:
    """A single QR login session (device context + cookie jar + poll URL)."""

    def __init__(self):
        self._device_id = secrets.token_hex(16)
        self._user_agent = (
            f"Android-7.1.1-1.0.0-ONEPLUS A3010-136-{self._device_id} "
            "APP/xiaomi.smarthome APPV/62830"
        )
        self._session: Optional[aiohttp.ClientSession] = None
        self._poll_url = ""
        self._poll_count = 0
        # A Xiaomi lp endpoint can only be consumed by ONE in-flight long-poll.
        # The frontend short-polls every 2s; if each poll fired its own 35s
        # long-poll they would stack up and steal the scan-confirmation event.
        # We coalesce concurrent polls: one long-poll runs, the rest read the
        # cached last state immediately.
        self._polling = False
        self._last_state = STATE_WAITING
        self._last_message = "等待扫码"
        self._last_cookie = ""
        self._last_user_id = ""

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # unsafe=True lets the Xiaomi service cookies persist across the
            # account.xiaomi.com endpoints involved in the handshake.
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(unsafe=True),
                timeout=aiohttp.ClientTimeout(total=20),
            )
        return self._session

    async def start(self) -> dict:
        """Fetch the QR code and long-poll URL.

        Returns ``{"qrcode": str, "login_url": str, "lp": str}``.
        """
        session = await self._ensure_session()
        headers = {"User-Agent": self._user_agent}

        # Step 1: obtain the signature parameters.
        async with session.get(
            _SERVICE_LOGIN_URL,
            params={"sid": "mijia", "_json": "true"},
            headers=headers,
            cookies={"sdkVersion": "3.8.6", "deviceId": self._device_id},
        ) as response:
            text = await response.text()
            data = json.loads(_strip_jsonp_prefix(text))

        sign = data.get("_sign")
        qs = data.get("qs")
        callback = data.get("callback")
        if not sign or not qs or not callback:
            raise RuntimeError("serviceLogin 响应缺少必要参数")

        # Step 2: obtain the QR image, login URL and long-poll URL.
        params = {
            "_qrsize": "240",
            "qs": qs,
            "sid": "mijia",
            "_sign": sign,
            "callback": callback,
            "_json": "true",
            "_dc": str(int(time.time() * 1000)),
        }
        async with session.get(_LOGIN_URL_ENDPOINT, params=params, headers=headers) as response:
            text = await response.text()
            data = json.loads(_strip_jsonp_prefix(text))

        lp = data.get("lp")
        if not lp:
            raise RuntimeError("loginUrl 响应缺少长轮询地址")

        self._poll_url = lp
        return {
            "qrcode": data.get("qr") or data.get("loginUrl") or "",
            "login_url": data.get("loginUrl") or "",
            "lp": lp,
        }

    async def poll(self) -> dict:
        """Poll once, coalescing concurrent polls into a single long-poll.

        Returns a dict with ``state`` and ``message``; a ``confirmed`` result
        additionally carries ``cookie`` and ``user_id``.
        """
        if not self._poll_url:
            raise RuntimeError("会话未启动")

        # A long-poll is already in flight; report the cached state instead of
        # stacking another request against the same lp URL.
        if self._polling:
            result = {"state": self._last_state, "message": self._last_message}
            if self._last_state == STATE_CONFIRMED:
                result["cookie"] = self._last_cookie
                result["user_id"] = self._last_user_id
            return result

        self._polling = True
        try:
            self._poll_count += 1
            if self._poll_count > MAX_POLL_COUNT:
                return {"state": STATE_EXPIRED, "message": "轮询次数超限，请重新获取二维码"}
            result = await self._do_poll()
            self._last_state = result["state"]
            self._last_message = result.get("message", "")
            self._last_cookie = result.get("cookie", "")
            self._last_user_id = result.get("user_id", "")
            return result
        finally:
            self._polling = False

    async def _do_poll(self) -> dict:
        """Perform a single blocking long-poll against the lp URL."""
        session = await self._ensure_session()
        headers = {"User-Agent": self._user_agent}
        try:
            async with session.get(
                self._poll_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=POLL_TIMEOUT_SECONDS),
            ) as response:
                if response.status == 403:
                    return {"state": STATE_EXPIRED, "message": "二维码已过期，请重新获取"}
                if response.status >= 400:
                    return {"state": STATE_FAILED, "message": f"轮询失败 (HTTP {response.status})"}
                text = await response.text()
        except asyncio.TimeoutError:
            return {"state": STATE_WAITING, "message": "等待扫码"}
        except Exception as exc:  # noqa: BLE001 - surface network errors to the UI
            return {"state": STATE_FAILED, "message": f"轮询异常: {exc}"}

        if not text or not text.strip():
            return {"state": STATE_WAITING, "message": "等待扫码"}

        try:
            data = json.loads(_strip_jsonp_prefix(text))
        except json.JSONDecodeError:
            return {"state": STATE_WAITING, "message": "等待扫码"}

        if data.get("code") != 0:
            return {"state": STATE_EXPIRED, "message": "二维码已失效，请重新获取"}

        user_id = _as_str(data.get("userId"))
        pass_token = _as_str(data.get("passToken"))
        if user_id and pass_token:
            return {
                "state": STATE_CONFIRMED,
                "message": "登录成功",
                "cookie": f"userId={user_id}; passToken={pass_token}",
                "user_id": user_id,
            }

        return {"state": STATE_SCANNED, "message": "已扫码，请在手机上确认登录"}

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None


class QRLoginManager:
    """Manages in-flight QR login sessions."""

    def __init__(self):
        self._sessions: dict[str, QRCodeLogin] = {}
        self._created_at: dict[str, float] = {}

    async def start(self) -> dict:
        """Start a session and download its QR image.

        Returns ``{"session_id": str, "qrcode_image": str, "login_url": str}``
        where ``qrcode_image`` is a base64 data URL (empty when the download
        failed, in which case the frontend falls back to ``login_url``).
        """
        self._cleanup_expired()
        qr = QRCodeLogin()
        info = await qr.start()
        session_id = secrets.token_hex(16)
        self._sessions[session_id] = qr
        self._created_at[session_id] = time.time()

        qrcode_image = ""
        if info["qrcode"]:
            try:
                qrcode_image = await self._download_qr(qr, info["qrcode"])
            except Exception as exc:  # noqa: BLE001 - image is optional
                log.debug("Failed to download QR image: %s", exc)

        return {
            "session_id": session_id,
            "qrcode_image": qrcode_image,
            "login_url": info["login_url"],
        }

    async def _download_qr(self, qr: QRCodeLogin, url: str) -> str:
        session = await qr._ensure_session()
        async with session.get(url) as response:
            if response.status != 200:
                return ""
            content_type = response.headers.get("Content-Type", "image/png")
            data = await response.read()
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{content_type};base64,{encoded}"

    async def poll(self, session_id: str) -> dict:
        """Poll a session; terminal sessions are removed and closed."""
        qr = self._sessions.get(session_id)
        if qr is None:
            return {"state": STATE_EXPIRED, "message": "会话不存在或已过期"}

        result = await qr.poll()
        if result["state"] in _TERMINAL_STATES:
            self._sessions.pop(session_id, None)
            self._created_at.pop(session_id, None)
            await qr.close()
        return result

    def _cleanup_expired(self) -> None:
        now = time.time()
        stale = [
            sid for sid, created in self._created_at.items()
            if now - created > SESSION_TTL_SECONDS
        ]
        for sid in stale:
            self._sessions.pop(sid, None)
            self._created_at.pop(sid, None)

    async def close_all(self) -> None:
        for qr in self._sessions.values():
            await qr.close()
        self._sessions.clear()
        self._created_at.clear()
