"""Unit tests for the Xiaomi QR-code login helper (offline, no network)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from miairx.auth.qr_login import (
    QRCodeLogin,
    QRLoginManager,
    STATE_CONFIRMED,
    STATE_EXPIRED,
    STATE_FAILED,
    STATE_SCANNED,
    STATE_WAITING,
    _strip_jsonp_prefix,
)


class TestStripJsonpPrefix:
    def test_strips_prefix(self):
        assert _strip_jsonp_prefix("&&&START&&&{\"code\": 0}") == "{\"code\": 0}"

    def test_no_prefix(self):
        assert _strip_jsonp_prefix("{\"code\": 0}") == "{\"code\": 0}"


def _json_response(payload: dict, status: int = 200):
    response = AsyncMock()
    response.status = status
    response.text = AsyncMock(return_value=json.dumps(payload))
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    return response


class TestQRCodeLoginStart:
    @pytest.mark.asyncio
    async def test_start_parses_service_login_and_login_url(self):
        qr = QRCodeLogin()

        with patch.object(qr, "_ensure_session") as ensure:
            session = MagicMock()
            service_resp = _json_response({
                "_sign": "sig", "qs": "qsval", "callback": "http://cb",
            })
            login_resp = _json_response({
                "qr": "http://qr.png", "loginUrl": "http://login", "lp": "http://poll",
            })
            session.get = MagicMock(side_effect=[service_resp, login_resp])
            ensure.return_value = session

            info = await qr.start()

        assert info["qrcode"] == "http://qr.png"
        assert info["login_url"] == "http://login"
        assert info["lp"] == "http://poll"
        assert qr._poll_url == "http://poll"

    @pytest.mark.asyncio
    async def test_start_raises_without_sign_params(self):
        qr = QRCodeLogin()
        with patch.object(qr, "_ensure_session") as ensure:
            session = MagicMock()
            session.get = MagicMock(return_value=_json_response({"code": 0}))
            ensure.return_value = session
            with pytest.raises(RuntimeError):
                await qr.start()


class TestQRCodeLoginPoll:
    @pytest.mark.asyncio
    async def test_poll_confirmed_returns_cookie(self):
        qr = QRCodeLogin()
        qr._poll_url = "http://poll"
        with patch.object(qr, "_ensure_session") as ensure:
            session = MagicMock()
            session.get = MagicMock(return_value=_json_response({
                "code": 0, "userId": "12345", "passToken": "tok",
            }))
            ensure.return_value = session

            result = await qr.poll()

        assert result["state"] == STATE_CONFIRMED
        assert result["cookie"] == "userId=12345; passToken=tok"
        assert result["user_id"] == "12345"

    @pytest.mark.asyncio
    async def test_poll_scanned_without_token(self):
        qr = QRCodeLogin()
        qr._poll_url = "http://poll"
        with patch.object(qr, "_ensure_session") as ensure:
            session = MagicMock()
            session.get = MagicMock(return_value=_json_response({"code": 0}))
            ensure.return_value = session
            result = await qr.poll()

        assert result["state"] == STATE_SCANNED

    @pytest.mark.asyncio
    async def test_poll_403_is_expired(self):
        qr = QRCodeLogin()
        qr._poll_url = "http://poll"
        with patch.object(qr, "_ensure_session") as ensure:
            session = MagicMock()
            session.get = MagicMock(return_value=_json_response({}, status=403))
            ensure.return_value = session
            result = await qr.poll()

        assert result["state"] == STATE_EXPIRED

    @pytest.mark.asyncio
    async def test_poll_nonzero_code_is_expired(self):
        qr = QRCodeLogin()
        qr._poll_url = "http://poll"
        with patch.object(qr, "_ensure_session") as ensure:
            session = MagicMock()
            session.get = MagicMock(return_value=_json_response({"code": 1}))
            ensure.return_value = session
            result = await qr.poll()

        assert result["state"] == STATE_EXPIRED

    @pytest.mark.asyncio
    async def test_poll_http_error_is_failed(self):
        qr = QRCodeLogin()
        qr._poll_url = "http://poll"
        with patch.object(qr, "_ensure_session") as ensure:
            session = MagicMock()
            session.get = MagicMock(return_value=_json_response({}, status=500))
            ensure.return_value = session
            result = await qr.poll()

        assert result["state"] == STATE_FAILED

    @pytest.mark.asyncio
    async def test_poll_coalesces_concurrent_requests(self):
        """Concurrent polls must not stack multiple lp long-polls."""
        qr = QRCodeLogin()
        qr._poll_url = "http://poll"

        calls = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_do_poll():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return {"state": STATE_WAITING, "message": "等待扫码"}

        qr._do_poll = fake_do_poll

        task1 = asyncio.create_task(qr.poll())
        await started.wait()

        # A second poll arrives while the first long-poll is still in flight;
        # it must return the cached state immediately without a new lp request.
        result2 = await qr.poll()
        assert result2["state"] == STATE_WAITING
        assert calls == 1

        release.set()
        result1 = await task1
        assert result1["state"] == STATE_WAITING
        assert calls == 1


class TestQRLoginManager:
    @pytest.mark.asyncio
    async def test_poll_unknown_session_is_expired(self):
        manager = QRLoginManager()
        result = await manager.poll("does-not-exist")
        assert result["state"] == STATE_EXPIRED
