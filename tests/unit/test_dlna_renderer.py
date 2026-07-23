"""Unit tests for DLNA renderer"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from miairx.protocols.dlna.renderer import DlnaRenderer, TransportState
from miairx.const import (
    TRANSPORT_STATE_NO_MEDIA,
    TRANSPORT_STATE_STOPPED,
    TRANSPORT_STATE_PLAYING,
    TRANSPORT_STATE_PAUSED,
)


@pytest.fixture
def mock_speaker():
    """Mock speaker controller."""
    speaker = MagicMock()
    speaker.did = "test_did"
    speaker.device_id = "test_device_id"
    speaker.play_url = AsyncMock(return_value=True)
    speaker.pause = AsyncMock(return_value=True)
    speaker.stop = AsyncMock(return_value=True)
    speaker.set_volume = AsyncMock(return_value=True)
    speaker.get_volume = AsyncMock(return_value=50)
    speaker.get_status = AsyncMock(return_value=1)  # PLAYING
    return speaker


@pytest.fixture
def renderer(mock_speaker):
    """Create DlnaRenderer instance."""
    return DlnaRenderer(
        udn="test-udn-123",
        friendly_name="Test Speaker",
        speaker=mock_speaker,
        default_volume=50,
    )


@pytest.mark.asyncio
async def test_initial_state(renderer):
    """Test initial transport state."""
    assert renderer.transport_state == TransportState.NO_MEDIA
    assert renderer.current_uri == ""
    assert renderer.volume == 50
    assert renderer.mute is False


@pytest.mark.asyncio
async def test_set_av_transport_uri(renderer):
    """Test SetAVTransportURI."""
    result = await renderer.set_av_transport_uri("http://example.com/song.mp3")
    
    assert result is True
    assert renderer.current_uri == "http://example.com/song.mp3"
    assert renderer.transport_state == TransportState.STOPPED


@pytest.mark.asyncio
async def test_set_av_transport_uri_video_rejected(renderer):
    """Test that video files are rejected."""
    result = await renderer.set_av_transport_uri("http://example.com/video.mp4")
    
    assert result is False
    assert renderer.current_uri == ""


@pytest.mark.asyncio
async def test_play_success(renderer, mock_speaker):
    """Test successful play."""
    await renderer.set_av_transport_uri("http://example.com/song.mp3")
    result = await renderer.play()
    
    assert result is True
    assert renderer.transport_state == TransportState.PLAYING
    mock_speaker.play_url.assert_called_once()


@pytest.mark.asyncio
async def test_play_no_uri(renderer):
    """Test play without URI."""
    result = await renderer.play()
    
    assert result is False
    assert renderer.transport_state == TransportState.NO_MEDIA


@pytest.mark.asyncio
async def test_pause(renderer, mock_speaker):
    """Test pause."""
    await renderer.set_av_transport_uri("http://example.com/song.mp3")
    await renderer.play()
    result = await renderer.pause()
    
    assert result is True
    assert renderer.transport_state == TransportState.PAUSED
    mock_speaker.pause.assert_called_once()


@pytest.mark.asyncio
async def test_stop(renderer, mock_speaker):
    """Test stop."""
    await renderer.set_av_transport_uri("http://example.com/song.mp3")
    await renderer.play()
    result = await renderer.stop()
    
    assert result is True
    assert renderer.transport_state == TransportState.STOPPED
    mock_speaker.stop.assert_called_once()


@pytest.mark.asyncio
async def test_get_transport_info(renderer):
    """Test get_transport_info."""
    info = renderer.get_transport_info()
    
    assert "CurrentTransportState" in info
    assert "CurrentTransportStatus" in info
    assert "CurrentSpeed" in info


@pytest.mark.asyncio
async def test_get_position_info(renderer):
    """Test get_position_info."""
    info = renderer.get_position_info()
    
    assert "Track" in info
    assert "TrackDuration" in info
    assert "RelTime" in info
    assert "AbsTime" in info


@pytest.mark.asyncio
async def test_get_media_info(renderer):
    """Test get_media_info."""
    info = renderer.get_media_info()
    
    assert "NrTracks" in info
    assert "MediaDuration" in info
    assert "CurrentURI" in info
    assert "PlayMedium" in info


@pytest.mark.asyncio
async def test_set_volume(renderer, mock_speaker):
    """Test set_volume."""
    await renderer.set_volume(75)
    
    assert renderer.volume == 75
    mock_speaker.set_volume.assert_called_once_with(75)


@pytest.mark.asyncio
async def test_set_mute(renderer, mock_speaker):
    """Test set_mute."""
    await renderer.set_mute(True)
    
    assert renderer.mute is True
    mock_speaker.set_volume.assert_called_with(0)


@pytest.mark.asyncio
async def test_video_extensions():
    """Test video extension detection."""
    renderer = DlnaRenderer(
        udn="test",
        friendly_name="Test",
        speaker=MagicMock(),
    )
    
    assert renderer._is_video_uri("http://example.com/video.mp4") is True
    assert renderer._is_video_uri("http://example.com/video.mkv") is True
    assert renderer._is_video_uri("http://example.com/audio.mp3") is False
    assert renderer._is_video_uri("http://example.com/audio.flac") is False


@pytest.mark.asyncio
async def test_parse_duration():
    """Test duration parsing."""
    renderer = DlnaRenderer(
        udn="test",
        friendly_name="Test",
        speaker=MagicMock(),
    )
    
    assert renderer._parse_time("00:03:30") == 210.0
    assert renderer._parse_time("01:00:00") == 3600.0
    assert renderer._parse_time("00:00:00") == 0.0


@pytest.mark.asyncio
async def test_format_time():
    """Test time formatting."""
    renderer = DlnaRenderer(
        udn="test",
        friendly_name="Test",
        speaker=MagicMock(),
    )
    
    assert renderer._format_time(210.0) == "00:03:30"
    assert renderer._format_time(3600.0) == "01:00:00"
    assert renderer._format_time(0.0) == "00:00:00"
