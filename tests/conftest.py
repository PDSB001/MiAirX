"""Shared test fixtures for MiAirX tests"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from miairx.config.models import AppConfig, SpeakerConfig
from miairx.auth.manager import AuthManager
from miairx.speaker.controller import SpeakerController


@pytest.fixture
def event_loop():
    """Create event loop for tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_session():
    """Mock aiohttp session."""
    session = AsyncMock()
    session.closed = False
    return session


@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    return AppConfig(
        account="test_user",
        password="test_pass",
        mi_did="123456789",
        hostname="192.168.1.100",
        dlna_port=8200,
        web_port=8300,
        conf_path="/tmp/test_conf",
    )


@pytest.fixture
def sample_speaker():
    """Sample speaker configuration."""
    return SpeakerConfig(
        did="123456789",
        device_id="device_123",
        hardware="LX06",
        name="Test Speaker",
        dlna_name="Test DLNA Speaker",
        udn="uuid:test-udn-123",
    )


@pytest.fixture
def mock_auth(mock_session, sample_config):
    """Mock authentication manager."""
    auth = AuthManager(sample_config, mock_session)
    auth._logged_in = True
    auth.mina_service = AsyncMock()
    auth.miio_service = AsyncMock()
    # Mock the login method to avoid real API calls
    auth.login = AsyncMock()
    auth.ensure_login = AsyncMock()
    return auth


@pytest.fixture
def mock_speaker_controller(sample_speaker, mock_auth):
    """Mock speaker controller."""
    controller = SpeakerController(sample_speaker, mock_auth)
    return controller


@pytest.fixture
def mock_mina_service():
    """Mock MiNA service."""
    service = AsyncMock()
    service.device_list = AsyncMock(return_value=[
        {
            "miotDID": "123456789",
            "deviceID": "device_123",
            "hardware": "LX06",
            "name": "Test Speaker",
        }
    ])
    service.play_by_music_url = AsyncMock(return_value=True)
    service.play_by_url = AsyncMock(return_value=True)
    service.player_pause = AsyncMock(return_value=True)
    service.player_stop = AsyncMock(return_value=True)
    service.player_set_volume = AsyncMock(return_value=True)
    service.player_get_status = AsyncMock(return_value={
        "status": 1,
        "volume": 50,
        "current_song_url": "http://example.com/song.mp3",
    })
    return service


@pytest.fixture
def mock_account():
    """Mock MiAccount."""
    account = MagicMock()
    account.token = {
        "userId": "test_user",
        "passToken": "test_token",
        "deviceId": "test_device",
    }
    account.login = AsyncMock()
    return account
