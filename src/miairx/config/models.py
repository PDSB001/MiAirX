"""Pydantic data models for MiAirX configuration"""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class SpeakerConfig(BaseModel):
    """Configuration for a single Xiaomi speaker."""
    
    did: str = ""
    device_id: str = ""
    hardware: str = ""
    name: str = ""
    dlna_name: str = ""
    udn: str = ""
    use_music_api: bool = False
    compatibility_mode: Optional[bool] = None
    enabled: bool = True

    # Hardware models that don't support lossless formats
    _NON_LOSSLESS_HARDWARE: set[str] = {"L05B", "L05C", "LX06", "L16A"}

    def is_compatibility_mode(self) -> bool:
        """Check if speaker should use compatibility mode."""
        if self.compatibility_mode is not None:
            return self.compatibility_mode
        # Default: use music API for models in NEED_USE_PLAY_MUSIC_API
        from miairx.const import NEED_USE_PLAY_MUSIC_API
        for model in NEED_USE_PLAY_MUSIC_API:
            if model in self.hardware:
                return False
        return True

    def get_dlna_name(self) -> str:
        """Get DLNA display name for this speaker.

        Priority:
        1. Explicit dlna_name (user override)
        2. Friendly speaker name (e.g. "XiaoAI Speaker (L05C)")
        3. Auto-generated from DID

        We use an ASCII-safe English name as the primary value because
        some DLNA clients (notably NetEase Cloud Music on Android) reject
        or fail to display non-ASCII friendlyName values.
        """
        if self.dlna_name:
            return self.dlna_name
        if self.name:
            return self.name
        if self.did:
            return f"XiaoAI-{self.did}"
        return "XiaoAI Speaker"

    def ensure_udn(self) -> None:
        """Ensure UDN (Unique Device Name) is set."""
        if not self.udn:
            self.udn = f"uuid:{uuid.uuid5(uuid.NAMESPACE_DNS, f'miair-{self.did}')}"

    def needs_audio_conversion(self, content_type: str = "") -> bool:
        """Check if audio format needs conversion.
        
        Some speakers don't support lossless formats and need WAV conversion.
        """
        if self.hardware not in self._NON_LOSSLESS_HARDWARE:
            return False
        
        # Already playable format
        if content_type:
            ct = content_type.lower()
            if "mp3" in ct or "mpeg" in ct or "wav" in ct or "x-wav" in ct:
                return False
        
        return True


class AppConfig(BaseModel):
    """Main application configuration."""
    
    account: str = ""
    password: str = ""
    mi_did: str = ""
    cookie: str = ""
    hostname: str = ""
    dlna_port: int = 8200
    web_port: int = 8300
    airplay_port_start: int = 7000
    conf_path: str = "conf"
    verbose: bool = False
    proxy_enabled: bool = False
    auto_play_on_set_uri: bool = False
    auto_resume_on_interrupt: bool = False
    resume_delay_seconds: int = 5
    default_volume: int = 30
    follow_device_volume: bool = True
    enable_voice_control: bool = False
    auto_restart: bool = False
    voice_poll_interval: int = 1
    web_password: str = ""
    speakers: dict[str, SpeakerConfig] = Field(default_factory=dict)

    def __init__(self, **data):
        super().__init__(**data)
        # Apply environment variable fallbacks
        if not self.account:
            import os
            self.account = os.getenv("MI_USER", "")
        if not self.password:
            import os
            self.password = os.getenv("MI_PASS", "")
        if not self.mi_did:
            import os
            self.mi_did = os.getenv("MI_DID", "")
        if not self.web_password:
            import os
            self.web_password = os.getenv("MIAIR_WEB_PASSWORD", "")
        if not self.hostname:
            import os
            self.hostname = os.getenv("MIAIR_HOSTNAME", "")
        # hostname is deliberately NOT auto-detected here. A blank value is
        # resolved at point-of-use (Application.resolve_hostname) so the LAN
        # address follows DHCP changes instead of being pinned to a stale IP
        # inside the persisted config.json.
        
        # Validate resume_delay_seconds
        self.resume_delay_seconds = max(1, min(15, self.resume_delay_seconds))

    @property
    def log_file(self) -> str:
        """Log file path (dynamic calculation)."""
        import os
        return os.path.join(self.conf_path, "miair.log")

    @property
    def mi_token_home(self) -> str:
        """Mi token storage path."""
        import os
        return os.path.join(self.conf_path, ".mi.token")

    @property
    def config_file(self) -> str:
        """Configuration file path."""
        import os
        return os.path.join(self.conf_path, "config.json")

    def get_did_list(self) -> list[str]:
        """Get list of configured device DIDs."""
        if not self.mi_did:
            return []
        return [d.strip() for d in self.mi_did.split(",") if d.strip()]

    def get_speaker(self, did: str) -> SpeakerConfig:
        """Get or create SpeakerConfig for given DID."""
        if did not in self.speakers:
            self.speakers[did] = SpeakerConfig(did=did)
        speaker = self.speakers[did]
        speaker.ensure_udn()
        return speaker

    def get_enabled_speakers(self) -> list[SpeakerConfig]:
        """Get all enabled speakers."""
        result = []
        for did in self.get_did_list():
            speaker = self.get_speaker(did)
            if speaker.enabled:
                result.append(speaker)
        return result

    def get_airplay_ports(self, speaker_index: int) -> tuple[int, int]:
        """Return the fixed RTSP and audio HTTP ports for a speaker.

        Each enabled speaker owns two consecutive TCP ports. Keeping the
        allocation deterministic makes host-networked Docker deployments and
        LAN firewall rules practical.
        """
        if speaker_index < 0:
            raise ValueError("speaker_index must be non-negative")

        rtsp_port = self.airplay_port_start + speaker_index * 2
        audio_port = rtsp_port + 1
        if self.airplay_port_start < 1 or audio_port > 65535:
            raise ValueError(
                "AirPlay port range exceeds 1-65535; lower airplay_port_start "
                "or configure fewer speakers"
            )
        if rtsp_port in {self.dlna_port, self.web_port} or audio_port in {
            self.dlna_port,
            self.web_port,
        }:
            raise ValueError(
                "AirPlay ports overlap the DLNA or Web management port"
            )
        return rtsp_port, audio_port
