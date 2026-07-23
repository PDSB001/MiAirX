"""Unit tests for authentication manager"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from miairx.auth.manager import AuthManager
from miairx.auth.cookie import parse_cookie_string, mask_cookie_value, validate_cookie_data
from miairx.auth.errors import LoginError, TokenExpiredError, CaptchaRequiredError
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
    """Test login with cookie."""
    config = AppConfig(
        cookie="userId=123456; passToken=abcdef",
        conf_path="/tmp/test",
    )
    auth = AuthManager(config, mock_session)
    
    await auth.login()
    
    assert auth.is_logged_in() is True
    assert auth.account is not None
    assert auth.mina_service is not None


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
