"""Unit tests for speaker controller"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from miairx.speaker.controller import SpeakerController, SpeakerStatus
from miairx.speaker.retry import with_login_retry
from miairx.auth.errors import LoginError, TokenExpiredError
from miairx.core.errors import SpeakerError


@pytest.mark.asyncio
async def test_play_url_success(mock_speaker_controller, mock_mina_service):
    """Test successful play_url."""
    mock_speaker_controller.auth.mina_service = mock_mina_service
    
    # Set hardware to a model that uses play_by_music_api
    mock_speaker_controller.speaker.hardware = "LX05"
    
    result = await mock_speaker_controller.play_url("http://example.com/song.mp3")
    
    assert result is True
    mock_mina_service.play_by_music_url.assert_called_once()


@pytest.mark.asyncio
async def test_play_url_with_login_retry(mock_speaker_controller, mock_mina_service):
    """Test play_url with login retry."""
    mock_speaker_controller.auth.mina_service = mock_mina_service
    
    # Set hardware to a model that uses play_by_music_api
    mock_speaker_controller.speaker.hardware = "LX05"
    
    # First call fails with login error, second succeeds
    mock_mina_service.play_by_music_url.side_effect = [
        LoginError("Login failed"),
        True,
    ]
    
    result = await mock_speaker_controller.play_url("http://example.com/song.mp3")
    
    assert result is True
    assert mock_mina_service.play_by_music_url.call_count == 2


@pytest.mark.asyncio
async def test_pause_success(mock_speaker_controller, mock_mina_service):
    """Test successful pause."""
    mock_speaker_controller.auth.mina_service = mock_mina_service
    
    # Set hardware to a model that uses play_by_music_api
    mock_speaker_controller.speaker.hardware = "LX05"
    
    result = await mock_speaker_controller.pause()
    
    assert result is True
    mock_mina_service.player_stop.assert_called_once()  # Uses stop for pause


@pytest.mark.asyncio
async def test_stop_success(mock_speaker_controller, mock_mina_service):
    """Test successful stop."""
    mock_speaker_controller.auth.mina_service = mock_mina_service
    
    result = await mock_speaker_controller.stop()
    
    assert result is True
    mock_mina_service.player_stop.assert_called_once()


@pytest.mark.asyncio
async def test_set_volume_success(mock_speaker_controller, mock_mina_service):
    """Test successful set_volume."""
    mock_speaker_controller.auth.mina_service = mock_mina_service
    
    result = await mock_speaker_controller.set_volume(50)
    
    assert result is True
    mock_mina_service.player_set_volume.assert_called_once_with(
        mock_speaker_controller.device_id, 50
    )


@pytest.mark.asyncio
async def test_get_volume_success(mock_speaker_controller, mock_mina_service):
    """Test successful get_volume."""
    mock_speaker_controller.auth.mina_service = mock_mina_service
    
    volume = await mock_speaker_controller.get_volume()
    
    assert volume == 50
    mock_mina_service.player_get_status.assert_called_once()


@pytest.mark.asyncio
async def test_get_status_success(mock_speaker_controller, mock_mina_service):
    """Test successful get_status."""
    mock_speaker_controller.auth.mina_service = mock_mina_service
    
    status = await mock_speaker_controller.get_status()
    
    assert status == SpeakerStatus.PLAYING
    mock_mina_service.player_get_status.assert_called_once()


@pytest.mark.asyncio
async def test_login_retry_decorator():
    """Test that login retry decorator works correctly."""
    mock_auth = MagicMock()
    mock_auth.invalidate_session = MagicMock()
    mock_auth.login = AsyncMock()
    
    call_count = 0
    
    class TestClass:
        def __init__(self):
            self.auth = mock_auth
        
        @with_login_retry
        async def test_method(self):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise LoginError("Login failed")
            return "success"
    
    obj = TestClass()
    result = await obj.test_method()
    
    assert result == "success"
    assert call_count == 2
    mock_auth.invalidate_session.assert_called_once()
    mock_auth.login.assert_called_once()
