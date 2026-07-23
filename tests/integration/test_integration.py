"""Integration tests for MiAirX"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from miairx.config.models import AppConfig, SpeakerConfig
from miairx.protocols.dlna.renderer import DlnaRenderer, TransportState
from miairx.protocols.dlna.soap import SoapHandler, parse_soap_action, parse_soap_body
from miairx.media.formats import AudioFormat, detect_audio_format
from miairx.media.transcoder import AudioTranscoder


@pytest.fixture
def config():
    """Test configuration."""
    return AppConfig(
        account="test_user",
        password="test_pass",
        mi_did="123456789",
        hostname="192.168.1.100",
        dlna_port=8200,
        web_port=8300,
        default_volume=50,
    )


@pytest.fixture
def speaker():
    """Test speaker configuration."""
    return SpeakerConfig(
        did="123456789",
        device_id="device_123",
        hardware="LX06",
        name="Test Speaker",
        dlna_name="Test DLNA Speaker",
        udn="uuid:test-udn-123",
    )


@pytest.fixture
def mock_speaker_controller():
    """Mock speaker controller."""
    controller = MagicMock()
    controller.did = "123456789"
    controller.device_id = "device_123"
    controller.play_url = AsyncMock(return_value=True)
    controller.pause = AsyncMock(return_value=True)
    controller.stop = AsyncMock(return_value=True)
    controller.set_volume = AsyncMock(return_value=True)
    controller.get_volume = AsyncMock(return_value=50)
    controller.get_status = AsyncMock(return_value=1)
    return controller


@pytest.fixture
def renderer(speaker, mock_speaker_controller, config):
    """Test DLNA renderer."""
    return DlnaRenderer(
        udn=speaker.udn,
        friendly_name=speaker.get_dlna_name(),
        speaker=mock_speaker_controller,
        default_volume=config.default_volume,
        config=config,
    )


class TestDlnaWorkflow:
    """Integration tests for DLNA workflow."""

    @pytest.mark.asyncio
    async def test_full_play_cycle(self, renderer, mock_speaker_controller):
        """Test complete play/pause/stop cycle."""
        # Set URI
        result = await renderer.set_av_transport_uri("http://example.com/song.mp3")
        assert result is True
        assert renderer.transport_state == TransportState.STOPPED

        # Play
        result = await renderer.play()
        assert result is True
        assert renderer.transport_state == TransportState.PLAYING
        mock_speaker_controller.play_url.assert_called_once()

        # Pause
        result = await renderer.pause()
        assert result is True
        assert renderer.transport_state == TransportState.PAUSED
        mock_speaker_controller.pause.assert_called_once()

        # Stop
        result = await renderer.stop()
        assert result is True
        assert renderer.transport_state == TransportState.STOPPED
        mock_speaker_controller.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_volume_control(self, renderer, mock_speaker_controller):
        """Test volume control workflow."""
        # Set volume
        await renderer.set_volume(75)
        assert renderer.volume == 75
        mock_speaker_controller.set_volume.assert_called_with(75)

        # Get volume
        volume = await renderer.get_volume()
        assert volume == 50  # Mock returns 50

        # Mute
        await renderer.set_mute(True)
        assert renderer.mute is True

        # Unmute
        await renderer.set_mute(False)
        assert renderer.mute is False

    @pytest.mark.asyncio
    async def test_soap_workflow(self, renderer):
        """Test SOAP request handling workflow."""
        # Parse SOAP action
        service_urn, action = parse_soap_action(
            '"urn:schemas-upnp-org:service:AVTransport:1#Play"'
        )
        assert service_urn == "urn:schemas-upnp-org:service:AVTransport:1"
        assert action == "Play"

        # Set URI first
        await renderer.set_av_transport_uri("http://example.com/song.mp3")

        # Handle Play action
        response, status = await SoapHandler.handle_request(
            renderer, service_urn, action, {}
        )
        assert status == 200
        assert "PlayResponse" in response

    @pytest.mark.asyncio
    async def test_video_rejection(self, renderer):
        """Test that video files are rejected."""
        result = await renderer.set_av_transport_uri("http://example.com/video.mp4")
        assert result is False
        assert renderer.current_uri == ""


class TestMediaFormats:
    """Integration tests for media format detection."""

    def test_mp3_detection(self):
        """Test MP3 format detection."""
        # MP3 with sync word
        data = b"\xff\xfb\x90\x00" + b"\x00" * 100
        assert detect_audio_format(data) == AudioFormat.MP3

        # MP3 with ID3 header
        data = b"ID3" + b"\x00" * 100
        assert detect_audio_format(data) == AudioFormat.MP3

    def test_flac_detection(self):
        """Test FLAC format detection."""
        data = b"fLaC" + b"\x00" * 100
        assert detect_audio_format(data) == AudioFormat.FLAC

    def test_wav_detection(self):
        """Test WAV format detection."""
        data = b"RIFF" + b"\x00" * 100
        assert detect_audio_format(data) == AudioFormat.WAV

    def test_ogg_detection(self):
        """Test OGG format detection."""
        data = b"OggS" + b"\x00" * 100
        assert detect_audio_format(data) == AudioFormat.OGG

    def test_filename_detection(self):
        """Test format detection by filename."""
        assert detect_audio_format(b"", "song.mp3") == AudioFormat.MP3
        assert detect_audio_format(b"", "song.flac") == AudioFormat.FLAC
        assert detect_audio_format(b"", "song.wav") == AudioFormat.WAV


class TestTranscoder:
    """Integration tests for audio transcoding."""

    @pytest.mark.asyncio
    async def test_transcoder_availability(self):
        """Test transcoder FFmpeg detection."""
        transcoder = AudioTranscoder()
        # FFmpeg may or may not be available in test environment
        assert isinstance(transcoder.is_available, bool)

    @pytest.mark.asyncio
    async def test_transcoder_no_ffmpeg(self):
        """Test transcoder behavior without FFmpeg."""
        transcoder = AudioTranscoder(ffmpeg_path="/nonexistent/ffmpeg")
        assert transcoder.is_available is False

        result = await transcoder.to_wav(b"test", AudioFormat.MP3)
        assert result is None


class TestSoapParsing:
    """Integration tests for SOAP parsing."""

    def test_full_soap_request(self):
        """Test complete SOAP request parsing."""
        body = """<?xml version="1.0" encoding="UTF-8"?>
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
          <s:Body>
            <u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
              <InstanceID>0</InstanceID>
              <CurrentURI>http://example.com/song.mp3</CurrentURI>
              <CurrentURIMetaData></CurrentURIMetaData>
            </u:SetAVTransportURI>
          </s:Body>
        </s:Envelope>"""

        params = parse_soap_body(body)
        assert params["InstanceID"] == "0"
        assert params["CurrentURI"] == "http://example.com/song.mp3"

    def test_soap_action_parsing(self):
        """Test SOAP action parsing."""
        # Valid action
        service_urn, action = parse_soap_action(
            '"urn:schemas-upnp-org:service:AVTransport:1#Play"'
        )
        assert service_urn == "urn:schemas-upnp-org:service:AVTransport:1"
        assert action == "Play"

        # Invalid action
        service_urn, action = parse_soap_action("InvalidAction")
        assert service_urn == ""
        assert action == "InvalidAction"


class TestConfiguration:
    """Integration tests for configuration."""

    def test_config_creation(self, config):
        """Test configuration creation."""
        assert config.account == "test_user"
        assert config.dlna_port == 8200
        assert config.web_port == 8300
        assert config.default_volume == 50

    def test_speaker_config(self, speaker):
        """Test speaker configuration."""
        assert speaker.did == "123456789"
        assert speaker.name == "Test Speaker"
        assert speaker.get_dlna_name() == "Test DLNA Speaker"

    def test_speaker_udn_generation(self, speaker):
        """Test UDN generation."""
        speaker.ensure_udn()
        assert speaker.udn.startswith("uuid:")
        assert len(speaker.udn) > 10
