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
        hardware = self.hardware or "Speaker"
        return f"XiaoAI {hardware} ({self.did})"

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
        if not self.hostname:
            import os
            self.hostname = os.getenv("MIAIR_HOSTNAME", "")
        if not self.hostname:
            self.hostname = self._detect_local_ip()
        
        # Validate resume_delay_seconds
        self.resume_delay_seconds = max(1, min(15, self.resume_delay_seconds))

    @staticmethod
    def _detect_local_ip() -> str:
        """Auto-detect local LAN IP address."""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

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
