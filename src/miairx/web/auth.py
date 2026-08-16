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

from aiohttp import web

log = logging.getLogger(__name__)

_COOKIE_NAME = "miairx_token"
_TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 days
_SALT = b"miairx-web-session-v1"

# Paths that never require a token so the login screen can bootstrap.
_PUBLIC_PATHS = {
    "/",
    "/legacy",
    "/favicon.ico",
    "/api/auth/login",
    "/api/auth/status",
}


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

    try:
        data = await request.json()
    except Exception:
        data = {}

    provided = str(data.get("password", ""))
    if not hmac.compare_digest(provided.encode("utf-8"), password.encode("utf-8")):
        return web.json_response({
            "success": False,
            "error": "密码错误",
        }, status=401)

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
