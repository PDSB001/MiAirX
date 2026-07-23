"""Unit tests for configuration models"""

import pytest
from pydantic import ValidationError

from miairx.config.models import AppConfig, SpeakerConfig


class TestSpeakerConfig:
    """Tests for SpeakerConfig model."""

    def test_default_values(self):
        """Test default configuration values."""
        config = SpeakerConfig()
        assert config.did == ""
        assert config.device_id == ""
        assert config.hardware == ""
        assert config.name == ""
        assert config.enabled is True

    def test_custom_values(self):
        """Test custom configuration values."""
        config = SpeakerConfig(
            did="123",
            device_id="device_123",
            hardware="LX06",
            name="Test Speaker",
            enabled=False,
        )
        assert config.did == "123"
        assert config.device_id == "device_123"
        assert config.hardware == "LX06"
        assert config.name == "Test Speaker"
        assert config.enabled is False

    def test_ensure_udn(self):
        """Test UDN generation."""
        config = SpeakerConfig(did="123")
        assert config.udn == ""
        config.ensure_udn()
        assert config.udn != ""
        assert config.udn.startswith("uuid:")

    def test_get_dlna_name(self):
        """Test DLNA name generation."""
        # With dlna_name
        config = SpeakerConfig(dlna_name="Custom Name")
        assert config.get_dlna_name() == "Custom Name"

        # With name only
        config = SpeakerConfig(name="Speaker Name")
        assert config.get_dlna_name() == "Speaker Name"

        # With did only
        config = SpeakerConfig(did="123")
        assert config.get_dlna_name() == "XiaoAI-123"

    def test_needs_audio_conversion(self):
        """Test audio conversion requirement."""
        # Non-lossless hardware
        config = SpeakerConfig(hardware="L05B")
        assert config.needs_audio_conversion("audio/flac") is True

        # Already MP3
        assert config.needs_audio_conversion("audio/mpeg") is False

        # Lossless hardware (not in _NON_LOSSLESS_HARDWARE)
        config = SpeakerConfig(hardware="LX05")
        assert config.needs_audio_conversion("audio/flac") is False


class TestAppConfig:
    """Tests for AppConfig model."""

    def test_default_values(self):
        """Test default configuration values."""
        config = AppConfig()
        assert config.dlna_port == 8200
        assert config.web_port == 8300
        assert config.verbose is False
        assert config.auto_restart is False

    def test_custom_values(self):
        """Test custom configuration values."""
        config = AppConfig(
            account="test_user",
            password="test_pass",
            dlna_port=9000,
            web_port=9001,
            verbose=True,
        )
        assert config.account == "test_user"
        assert config.password == "test_pass"
        assert config.dlna_port == 9000
        assert config.web_port == 9001
        assert config.verbose is True

    def test_get_did_list(self):
        """Test DID list parsing."""
        config = AppConfig(mi_did="123,456,789")
        did_list = config.get_did_list()
        assert len(did_list) == 3
        assert "123" in did_list
        assert "456" in did_list
        assert "789" in did_list

    def test_get_did_list_empty(self):
        """Test empty DID list."""
        config = AppConfig(mi_did="")
        assert config.get_did_list() == []

    def test_get_speaker(self):
        """Test speaker creation and retrieval."""
        config = AppConfig(mi_did="123")
        speaker = config.get_speaker("123")
        assert speaker.did == "123"
        assert speaker.udn != ""  # Should be auto-generated

    def test_get_enabled_speakers(self):
        """Test enabled speakers filtering."""
        config = AppConfig(
            mi_did="123,456",
            speakers={
                "123": SpeakerConfig(did="123", enabled=True),
                "456": SpeakerConfig(did="456", enabled=False),
            },
        )
        enabled = config.get_enabled_speakers()
        assert len(enabled) == 1
        assert enabled[0].did == "123"
