"""Unit tests for the Xiaomi QR-code login helper (offline, no network)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from miairx.auth.qr_login import (
    MAX_POLL_COUNT,
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
    async def test_poll_confirmed_exchanges_service_token(self):
        """Confirmed poll must extract location and exchange the serviceToken."""
        qr = QRCodeLogin()
        qr._poll_url = "http://poll"
        with patch.object(qr, "_ensure_session") as ensure:
            session = MagicMock()
            session.get = MagicMock(return_value=_json_response({
                "code": 0, "userId": "12345", "passToken": "V1:encrypted",
                "ssecurity": "sec", "nonce": "nonce123",
                "location": "https://sts.example/cb", "cUserId": "cuser",
            }))
            ensure.return_value = session
            with patch.object(qr, "_fetch_service_token", new=AsyncMock(return_value="st_xyz")) as fetch:
                result = await qr.poll()

        assert result["state"] == STATE_CONFIRMED
        assert result["cookie"] == "userId=12345; passToken=V1:encrypted"
        assert result["service_token"] == "st_xyz"
        assert result["ssecurity"] == "sec"
        fetch.assert_awaited_once_with("https://sts.example/cb", "nonce123", "sec")

    @pytest.mark.asyncio
    async def test_fetch_service_token_from_callback_cookie(self):
        """_fetch_service_token reads serviceToken from the callback Set-Cookie."""
        qr = QRCodeLogin()

        session = MagicMock()
        resp = AsyncMock()
        resp.read = AsyncMock()
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        cookie = MagicMock()
        cookie.value = "st_from_cookie"
        resp.cookies = {"serviceToken": cookie}
        session.get = MagicMock(return_value=resp)

        with patch.object(qr, "_ensure_session", new=AsyncMock(return_value=session)):
            token = await qr._fetch_service_token("https://sts.example/cb", "nonce", "sec")

        assert token == "st_from_cookie"

    @pytest.mark.asyncio
    async def test_fetch_service_token_falls_back_to_client_sign(self):
        """When the bare callback yields no token, fall back to clientSign URL."""
        qr = QRCodeLogin()

        session = MagicMock()
        empty_resp = AsyncMock()
        empty_resp.read = AsyncMock()
        empty_resp.__aenter__ = AsyncMock(return_value=empty_resp)
        empty_resp.__aexit__ = AsyncMock(return_value=False)
        empty_resp.cookies = {}

        ok_resp = AsyncMock()
        ok_resp.read = AsyncMock()
        ok_resp.__aenter__ = AsyncMock(return_value=ok_resp)
        ok_resp.__aexit__ = AsyncMock(return_value=False)
        cookie = MagicMock()
        cookie.value = "st_fallback"
        ok_resp.cookies = {"serviceToken": cookie}

        session.get = MagicMock(side_effect=[empty_resp, ok_resp])

        with patch.object(qr, "_ensure_session", new=AsyncMock(return_value=session)):
            token = await qr._fetch_service_token("https://sts.example/cb", "nonce", "sec")

        assert token == "st_fallback"
        # Second call must have included the clientSign query param.
        urls = [call.args[0] for call in session.get.call_args_list]
        assert "clientSign=" in urls[1]

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
    async def test_poll_increments_count_and_caps(self):
        """poll() must enforce MAX_POLL_COUNT."""
        qr = QRCodeLogin()
        qr._poll_url = "http://poll"
        qr._poll_count = MAX_POLL_COUNT

        result = await qr.poll()

        assert result["state"] == STATE_EXPIRED


class TestQRLoginManager:
    @pytest.mark.asyncio
    async def test_poll_unknown_session_is_expired(self):
        manager = QRLoginManager()
        result = await manager.poll("does-not-exist")
        assert result["state"] == STATE_EXPIRED
