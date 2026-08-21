"""Unit tests for authentication manager"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from miairx.auth.cookie import mask_cookie_value, parse_cookie_string, validate_cookie_data
from miairx.auth.errors import TokenExpiredError
from miairx.auth.manager import (
    XIAOMI_STATUS_EXPIRED,
    XIAOMI_STATUS_NETWORK_ERROR,
    XIAOMI_STATUS_SERVICE_UNAVAILABLE,
    AuthManager,
)
from miairx.config.models import AppConfig


class TestCookieUtils:
    """Tests for cookie utility functions."""

    def test_parse_cookie_string(self):
        """Test cookie string parsing."""
        cookie_str = "userId=123456; passToken=abcdef; other=value"
        result = parse_cookie_string(cookie_str)
        
        assert result["userId"] == "123456"
        assert result["passToken"] == "abcdef"
        assert "other" not in result

    def test_parse_cookie_string_empty(self):
        """Test empty cookie string parsing."""
        result = parse_cookie_string("")
        assert result == {}

    def test_mask_cookie_value(self):
        """Test cookie value masking."""
        assert mask_cookie_value("1234567890") == "1234****"
        assert mask_cookie_value("short") == "****"
        assert mask_cookie_value("") == ""

    def test_validate_cookie_data_valid(self):
        """Test valid cookie data validation."""
        token_data = {"userId": "123", "passToken": "abc"}
        is_valid, error = validate_cookie_data(token_data)
        
        assert is_valid is True
        assert error is None

    def test_validate_cookie_data_missing_user_id(self):
        """Test cookie data validation with missing userId."""
        token_data = {"passToken": "abc"}
        is_valid, error = validate_cookie_data(token_data)
        
        assert is_valid is False
        assert "userId" in error

    def test_validate_cookie_data_missing_pass_token(self):
        """Test cookie data validation with missing passToken."""
        token_data = {"userId": "123"}
        is_valid, error = validate_cookie_data(token_data)
        
        assert is_valid is False
        assert "passToken" in error


@pytest.mark.asyncio
async def test_auth_manager_login_with_cookie(mock_session):
    """Test cookie login seeds the token and skips the login() call."""
    config = AppConfig(
        cookie="userId=123456; passToken=abcdef",
        conf_path="/tmp/test",
    )
    auth = AuthManager(config, mock_session)

    with patch("miairx.auth.manager.MiAccount") as MiAccountMock:
        mock_account = MagicMock()
        mock_account.token = None
        MiAccountMock.return_value = mock_account
        await auth.login()

    assert auth.is_logged_in() is True
    assert auth.account is not None
    assert auth.mina_service is not None
    # Cookie login must NOT call the miservice login() (which expects a
    # password-login response and would crash on KeyError('passToken')).
    assert auth.account.token["userId"] == "123456"
    assert auth.account.token["passToken"] == "abcdef"
    mock_account.login.assert_not_called()


@pytest.mark.asyncio
async def test_auth_manager_login_with_account(mock_session, mock_account):
    """Test login with account/password."""
    config = AppConfig(
        account="test_user",
        password="test_pass",
        conf_path="/tmp/test",
    )
    auth = AuthManager(config, mock_session)
    
    with patch("miairx.auth.manager.MiAccount", return_value=mock_account):
        await auth.login()
    
    assert auth.is_logged_in() is True
    mock_account.login.assert_called_once_with("micoapi")


@pytest.mark.asyncio
async def test_auth_manager_login_failure(mock_session):
    """Test login failure handling."""
    config = AppConfig(
        account="test_user",
        password="wrong_pass",
        conf_path="/tmp/test",
    )
    auth = AuthManager(config, mock_session)
    
    mock_account = MagicMock()
    mock_account.login = AsyncMock(side_effect=Exception("Login failed"))
    
    with patch("miairx.auth.manager.MiAccount", return_value=mock_account):
        # Login should not raise exception, but log error and continue
        await auth.login()
    
    # Service should continue without login
    assert auth.is_logged_in() is False
    assert auth.login_status() == XIAOMI_STATUS_EXPIRED


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TokenExpiredError("token expired"), XIAOMI_STATUS_EXPIRED),
        (TimeoutError("request timed out"), XIAOMI_STATUS_NETWORK_ERROR),
        (RuntimeError("503 service unavailable"), XIAOMI_STATUS_SERVICE_UNAVAILABLE),
    ],
)
def test_xiaomi_error_categories(error, expected):
    assert AuthManager.classify_login_error(error) == expected


@pytest.mark.asyncio
async def test_auth_manager_invalidate_session(mock_session):
    """Test session invalidation."""
    config = AppConfig(conf_path="/tmp/test")
    auth = AuthManager(config, mock_session)
    auth._logged_in = True
    
    auth.invalidate_session()
    
    assert auth.is_logged_in() is False


@pytest.mark.asyncio
async def test_auth_manager_ensure_login(mock_session, mock_account):
    """Test ensure_login."""
    config = AppConfig(
        account="test_user",
        password="test_pass",
        conf_path="/tmp/test",
    )
    auth = AuthManager(config, mock_session)
    
    with patch("miairx.auth.manager.MiAccount", return_value=mock_account):
        await auth.ensure_login()
    
    assert auth.is_logged_in() is True


@pytest.mark.asyncio
async def test_auth_manager_get_device_list(mock_session, mock_mina_service):
    """Test get_device_list."""
    config = AppConfig(conf_path="/tmp/test")
    auth = AuthManager(config, mock_session)
    auth._logged_in = True
    auth.mina_service = mock_mina_service
    
    devices = await auth.get_device_list()
    
    assert len(devices) == 1
    assert devices[0]["miotDID"] == "123456789"


class TestSpeakerDiscovery:
    """Tests for automatic speaker discovery from the cloud device list."""

    def test_identifies_known_speaker_models(self):
        speakers = [
            {"hardware": "LX04"},
            {"hardware": "X08A"},
            {"hardware": "S12A"},
            {"hardware": "OH2P"},
            {"hardware": "L15A"},
        ]
        for device in speakers:
            assert AuthManager.is_speaker_device(device), device

    def test_rejects_non_speaker_devices(self):
        non_speakers = [
            {"hardware": "MIBOX3"},
            {"hardware": "AIR_CONDITIONER"},
            {"hardware": ""},
            {},
        ]
        for device in non_speakers:
            assert not AuthManager.is_speaker_device(device), device

    @pytest.mark.asyncio
    async def test_discover_speakers_filters_cloud_list(self, mock_session, mock_mina_service):
        mock_mina_service.device_list = AsyncMock(return_value=[
            {"miotDID": "1", "hardware": "LX06", "name": "Speaker A"},
            {"miotDID": "2", "hardware": "MIBOX3", "name": "TV Box"},
            {"miotDID": "3", "hardware": "X08C", "name": "Speaker B"},
            {"miotDID": "4", "name": "Unknown"},
        ])
        config = AppConfig(conf_path="/tmp/test")
        auth = AuthManager(config, mock_session)
        auth._logged_in = True
        auth.mina_service = mock_mina_service

        discovered = await auth.discover_speakers()

        assert [d["miotDID"] for d in discovered] == ["1", "3"]
