"""Unit tests for configuration models"""

import socket

import pytest

from miairx.config.discovery import detect_local_ip
from miairx.config.models import AppConfig, SpeakerConfig


def test_detect_local_ip_uses_default_route(monkeypatch):
    """Automatic setup uses the IPv4 selected by the host default route."""

    class FakeSocket:
        def connect(self, destination):
            assert destination == ("223.5.5.5", 80)

        @staticmethod
        def getsockname():
            return ("192.168.50.10", 12345)

        @staticmethod
        def close():
            return None

    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: FakeSocket())

    assert detect_local_ip() == "192.168.50.10"


def test_detect_local_ip_falls_back_to_lan_interface(monkeypatch):
    """A NAS without a default route can still select a private interface."""

    class DisconnectedSocket:
        @staticmethod
        def connect(_destination):
            raise OSError("no route")

        @staticmethod
        def close():
            return None

    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_args, **_kwargs: DisconnectedSocket(),
    )
    monkeypatch.setattr(socket, "gethostname", lambda: "fnos")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_DGRAM, 0, "", ("127.0.0.1", 0)),
            (socket.AF_INET, socket.SOCK_DGRAM, 0, "", ("192.168.50.20", 0)),
        ],
    )

    assert detect_local_ip() == "192.168.50.20"


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
        assert config.airplay_port_start == 7000
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

    def test_airplay_ports_are_deterministic(self):
        """Each speaker receives a stable RTSP/audio TCP pair."""
        config = AppConfig(airplay_port_start=7000)

        assert config.get_airplay_ports(0) == (7000, 7001)
        assert config.get_airplay_ports(1) == (7002, 7003)
        assert config.get_airplay_ports(49) == (7098, 7099)

    def test_airplay_ports_reject_overlap_with_http_services(self):
        """A bad custom range must fail before the server binds sockets."""
        config = AppConfig(dlna_port=8200, web_port=8300, airplay_port_start=8199)

        with pytest.raises(ValueError, match="overlap"):
            config.get_airplay_ports(0)

    def test_airplay_ports_reject_range_overflow(self):
        config = AppConfig(airplay_port_start=65535)

        with pytest.raises(ValueError, match="exceeds"):
            config.get_airplay_ports(0)

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
