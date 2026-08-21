"""Session token authentication for the MiAirX web management console.

The console is protected by an optional ``web_password``. When set, every
``/api/*`` endpoint (except the login endpoint itself) requires a signed
session token. Static assets and the index page remain public so the login
screen can load; the React client checks its own authentication state via
``/api/auth/status`` and shows the login form before querying anything else.

Tokens are stateless HMAC-signed strings so they survive application reloads
without any server-side session store, while remaining invalidated whenever
the configured password changes.
"""

import base64
import hashlib
import hmac
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache

from aiohttp import web

log = logging.getLogger(__name__)

_COOKIE_NAME = "miairx_token"
_TOKEN_TTL_SECONDS = 24 * 3600  # 24 hours
_SALT = b"miairx-web-session-v1"
_LOGIN_LIMITER_KEY = "login_rate_limiter"


@dataclass
class LoginRateLimiter:
    """Small in-memory limiter for repeated password failures by peer address."""

    max_failures: int = 5
    window_seconds: int = 5 * 60
    max_peers: int = 1024
    failures: dict[str, deque[float]] = field(default_factory=dict)

    def _prune(self, peer: str, now: float) -> deque[float]:
        attempts = self.failures.setdefault(peer, deque())
        cutoff = now - self.window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            self.failures.pop(peer, None)
            attempts = deque()
        return attempts

    def retry_after(self, peer: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        attempts = self._prune(peer, now)
        if len(attempts) < self.max_failures:
            return 0
        return max(1, int(self.window_seconds - (now - attempts[0])))

    def record_failure(self, peer: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        attempts = self._prune(peer, now)
        attempts.append(now)
        self.failures[peer] = attempts

        # Keep unauthenticated traffic from growing the peer map without bound.
        if len(self.failures) > self.max_peers:
            oldest_peer = min(
                self.failures,
                key=lambda item: self.failures[item][-1],
            )
            self.failures.pop(oldest_peer, None)
        return self.retry_after(peer, now)

    def reset(self, peer: str) -> None:
        self.failures.pop(peer, None)


def _request_peer(request: web.Request) -> str:
    """Return a stable direct peer identity without trusting proxy headers."""
    remote = getattr(request, "remote", None)
    if remote:
        return str(remote)
    transport = getattr(request, "transport", None)
    peername = transport.get_extra_info("peername") if transport else None
    return str(peername[0]) if peername else "unknown"


def _get_login_limiter(request: web.Request) -> LoginRateLimiter:
    limiter = request.app.get(_LOGIN_LIMITER_KEY)
    if limiter is None:
        limiter = LoginRateLimiter()
        request.app[_LOGIN_LIMITER_KEY] = limiter
    return limiter

# Paths that never require a token so the login screen can bootstrap.
_PUBLIC_PATHS = {
    "/",
    "/legacy",
    "/favicon.ico",
    "/api/auth/login",
    "/api/auth/status",
}


@lru_cache(maxsize=8)
def _derive_key(password: str) -> bytes:
    """Derive an HMAC key from the configured web password."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _SALT, 100_000)


def issue_token(password: str, now: float | None = None) -> str:
    """Create a signed session token valid for ``_TOKEN_TTL_SECONDS``."""
    now = time.time() if now is None else now
    expiry = int(now) + _TOKEN_TTL_SECONDS
    payload = str(expiry).encode("ascii")
    signature = hmac.new(_derive_key(password), payload, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(payload + b"." + signature).decode("ascii")
    return token


def verify_token(password: str, token: str | None, now: float | None = None) -> bool:
    """Return True if ``token`` is a valid, unexpired session token."""
    if not password or not token:
        return False
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        payload, signature = raw.split(b".", 1)
        expiry = int(payload.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return False

    now = time.time() if now is None else now
    if expiry < now:
        return False

    expected = hmac.new(_derive_key(password), payload, hashlib.sha256).digest()
    return hmac.compare_digest(signature, expected)


def _read_token(request: web.Request) -> str | None:
    """Extract the session token from the cookie or Authorization header."""
    cookie = request.cookies.get(_COOKIE_NAME)
    if cookie:
        return cookie
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):]
    return None


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Reject unauthenticated API requests when a web password is configured."""
    config = request.app.get("config")
    password = getattr(config, "web_password", "") if config else ""

    if not password:
        return await handler(request)

    path = request.path
    if path in _PUBLIC_PATHS or path.startswith("/static/"):
        return await handler(request)

    if not path.startswith("/api/"):
        return await handler(request)

    if verify_token(password, _read_token(request)):
        return await handler(request)

    return web.json_response({"success": False, "error": "未授权，请先登录"}, status=401)


async def handle_auth_status(request: web.Request) -> web.Response:
    """Report whether authentication is enabled and whether the client is logged in."""
    config = request.app["config"]
    password = getattr(config, "web_password", "") if config else ""
    authenticated = bool(password) and verify_token(password, _read_token(request))

    return web.json_response({
        "auth_enabled": bool(password),
        "authenticated": authenticated,
    })


async def handle_auth_login(request: web.Request) -> web.Response:
    """Validate the provided password and issue a session token cookie."""
    config = request.app["config"]
    password = getattr(config, "web_password", "") if config else ""

    if not password:
        return web.json_response({
            "success": False,
            "error": "后台未启用登录保护",
        }, status=400)

    peer = _request_peer(request)
    limiter = _get_login_limiter(request)
    retry_after = limiter.retry_after(peer)
    if retry_after:
        return web.json_response(
            {"success": False, "error": "登录尝试过多，请稍后重试"},
            status=429,
            headers={"Retry-After": str(retry_after)},
        )

    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    provided = str(data.get("password", ""))
    if not hmac.compare_digest(provided.encode("utf-8"), password.encode("utf-8")):
        retry_after = limiter.record_failure(peer)
        if retry_after:
            return web.json_response(
                {"success": False, "error": "登录尝试过多，请稍后重试"},
                status=429,
                headers={"Retry-After": str(retry_after)},
            )
        return web.json_response({
            "success": False,
            "error": "密码错误",
        }, status=401)

    limiter.reset(peer)
    token = issue_token(password)
    response = web.json_response({"success": True})
    response.set_cookie(
        _COOKIE_NAME,
        token,
        max_age=_TOKEN_TTL_SECONDS,
        httponly=True,
        samesite="Lax",
    )
    return response


async def handle_auth_logout(request: web.Request) -> web.Response:
    """Clear the session token cookie."""
    response = web.json_response({"success": True})
    response.del_cookie(_COOKIE_NAME)
    return response
