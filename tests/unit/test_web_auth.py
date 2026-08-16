"""Unit tests for web authentication helpers."""

import time

import pytest

from miairx.web.auth import (
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
        # Advance past the TTL
        assert not verify_token("secret-password", token, now=now + 8 * 24 * 3600)

    def test_malformed_token_rejected(self):
        assert not verify_token("secret-password", "not-a-valid-token")
        assert not verify_token("secret-password", "")
        assert not verify_token("secret-password", None)


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
