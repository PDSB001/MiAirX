"""Unit tests for web authentication helpers."""

from unittest.mock import AsyncMock

import pytest

from miairx.web.auth import (
    LoginRateLimiter,
    auth_middleware,
    handle_auth_login,
    handle_auth_status,
    issue_token,
    verify_token,
)


class TestToken:
    def test_roundtrip(self):
        token = issue_token("secret-password")
        assert verify_token("secret-password", token)

    def test_wrong_password_rejected(self):
        token = issue_token("secret-password")
        assert not verify_token("other-password", token)

    def test_expired_token_rejected(self):
        now = 1_000_000.0
        token = issue_token("secret-password", now=now)
        assert verify_token("secret-password", token, now=now + 24 * 3600 - 1)
        assert not verify_token("secret-password", token, now=now + 24 * 3600 + 1)

    def test_malformed_token_rejected(self):
        assert not verify_token("secret-password", "not-a-valid-token")
        assert not verify_token("secret-password", "")
        assert not verify_token("secret-password", None)


class TestLoginRateLimiter:
    def test_blocks_after_repeated_failures_and_expires(self):
        limiter = LoginRateLimiter(max_failures=3, window_seconds=60)

        assert limiter.record_failure("192.0.2.1", now=100) == 0
        assert limiter.record_failure("192.0.2.1", now=101) == 0
        assert limiter.record_failure("192.0.2.1", now=102) > 0
        assert limiter.retry_after("192.0.2.1", now=120) > 0
        assert limiter.retry_after("192.0.2.1", now=163) == 0

    def test_success_resets_peer_failures(self):
        limiter = LoginRateLimiter(max_failures=2, window_seconds=60)
        limiter.record_failure("192.0.2.1", now=100)
        limiter.reset("192.0.2.1")

        assert limiter.retry_after("192.0.2.1", now=101) == 0


class TestHandlers:
    @pytest.mark.asyncio
    async def test_login_success_sets_cookie(self):
        class Config:
            web_password = "secret-password"

        class Request:
            app = {"config": Config()}
            cookies = {}

            async def json(self):
                return {"password": "secret-password"}

        response = await handle_auth_login(Request())

        assert response.status == 200
        cookie = response.cookies.get("miairx_token")
        assert cookie is not None
        assert cookie["httponly"] is True

    @pytest.mark.asyncio
    async def test_login_wrong_password(self):
        class Config:
            web_password = "secret-password"

        class Request:
            app = {"config": Config()}
            cookies = {}

            async def json(self):
                return {"password": "wrong"}

        response = await handle_auth_login(Request())

        assert response.status == 401

    @pytest.mark.asyncio
    async def test_login_is_rate_limited_per_peer(self):
        class Config:
            web_password = "secret-password"

        app = {"config": Config()}

        class Request:
            remote = "192.0.2.1"
            cookies = {}

            def __init__(self):
                self.app = app

            async def json(self):
                return {"password": "wrong"}

        responses = [await handle_auth_login(Request()) for _ in range(5)]

        assert [response.status for response in responses] == [401, 401, 401, 401, 429]
        assert int(responses[-1].headers["Retry-After"]) > 0

    @pytest.mark.asyncio
    async def test_status_reports_authenticated(self):
        class Config:
            web_password = "secret-password"

        token = issue_token("secret-password")

        class Request:
            app = {"config": Config()}
            cookies = {"miairx_token": token}

        response = await handle_auth_status(Request())
        body = __import__("json").loads(response.text)

        assert body["auth_enabled"] is True
        assert body["authenticated"] is True

    @pytest.mark.asyncio
    async def test_middleware_rejects_missing_token(self):
        class Config:
            web_password = "secret-password"

        class Request:
            app = {"config": Config()}
            path = "/api/config"
            cookies = {}
            headers = {}

        handler = AsyncMock()
        response = await auth_middleware(Request(), handler)

        assert response.status == 401
        handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_middleware_accepts_valid_token(self):
        class Config:
            web_password = "secret-password"

        class Request:
            app = {"config": Config()}
            path = "/api/config"
            cookies = {"miairx_token": issue_token("secret-password")}
            headers = {}

        async def handler(_request):
            return "allowed"

        assert await auth_middleware(Request(), handler) == "allowed"
