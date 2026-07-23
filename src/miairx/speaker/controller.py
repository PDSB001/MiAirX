"""Speaker controller for MiAirX"""

import logging
from typing import Optional

from miairx.auth.manager import AuthManager
from miairx.auth.errors import LoginError, TokenExpiredError
from miairx.config.models import SpeakerConfig
from miairx.const import DEFAULT_AUDIO_ID, NEED_USE_PLAY_MUSIC_API
from miairx.core.errors import SpeakerError
from miairx.speaker.retry import with_login_retry

log = logging.getLogger(__name__)


class SpeakerStatus:
    """Speaker playback status."""
    
    STOPPED = 0
    PLAYING = 1
    PAUSED = 2


class SpeakerController:
    """Controls a single Xiaomi speaker."""

    # Class-level consecutive login failure counter
    _consecutive_login_failures: int = 0
    _LOGIN_FAILURE_RESTART_THRESHOLD = 6

    def __init__(self, speaker: SpeakerConfig, auth: AuthManager):
        self.speaker = speaker
        self.auth = auth
        self._last_volume: int = 50  # For unmute restore

    @classmethod
    def _check_and_trigger_restart(cls) -> None:
        """Check consecutive login failures and trigger restart if threshold reached."""
        if cls._consecutive_login_failures >= cls._LOGIN_FAILURE_RESTART_THRESHOLD:
            log.error(
                f"Consecutive login failures reached {cls._consecutive_login_failures}, "
                "triggering restart to recover service..."
            )
            from miairx.core.lifecycle import lifecycle
            lifecycle.trigger_shutdown()

    @property
    def device_id(self) -> str:
        """Get device ID."""
        return self.speaker.device_id

    @property
    def did(self) -> str:
        """Get device DID."""
        return self.speaker.did

    def _should_use_music_api(self) -> bool:
        """Check if should use music API for this speaker."""
        if self.speaker.is_compatibility_mode():
            return False
        return True

    @with_login_retry
    async def play_url(self, url: str) -> bool:
        """Play audio from URL."""
        try:
            await self.auth.ensure_login()
            if self._should_use_music_api():
                ret = await self.auth.mina_service.play_by_music_url(
                    self.device_id, url, audio_id=DEFAULT_AUDIO_ID
                )
                log.info(f"play_by_music_url device_id={self.device_id} ret={ret}")
            else:
                ret = await self.auth.mina_service.play_by_url(self.device_id, url)
                log.info(f"play_by_url device_id={self.device_id} ret={ret}")
            
            # Reset failure counter on success
            SpeakerController._consecutive_login_failures = 0
            return ret is not None
        except (LoginError, TokenExpiredError):
            # Re-raise login errors for retry decorator
            raise
        except Exception as e:
            log.error(f"play_url failed: {e}")
            SpeakerController._consecutive_login_failures += 1
            SpeakerController._check_and_trigger_restart()
            raise SpeakerError(f"Failed to play URL: {e}") from e

    @with_login_retry
    async def pause(self) -> bool:
        """Pause playback."""
        try:
            await self.auth.ensure_login()
            if self._should_use_music_api():
                # Some models using play_by_music_url don't update status correctly on pause
                # Use stop instead for pause semantics
                ret = await self.auth.mina_service.player_stop(self.device_id)
                log.info(f"player_stop(as pause) device_id={self.device_id} ret={ret}")
            else:
                ret = await self.auth.mina_service.player_pause(self.device_id)
                log.info(f"player_pause device_id={self.device_id} ret={ret}")
            
            SpeakerController._consecutive_login_failures = 0
            return True
        except Exception as e:
            log.error(f"pause failed: {e}")
            SpeakerController._consecutive_login_failures += 1
            SpeakerController._check_and_trigger_restart()
            raise SpeakerError(f"Failed to pause: {e}") from e

    @with_login_retry
    async def stop(self) -> bool:
        """Stop playback."""
        try:
            await self.auth.ensure_login()
            ret = await self.auth.mina_service.player_stop(self.device_id)
            log.info(f"player_stop device_id={self.device_id} ret={ret}")
            
            SpeakerController._consecutive_login_failures = 0
            return True
        except Exception as e:
            log.error(f"stop failed: {e}")
            SpeakerController._consecutive_login_failures += 1
            SpeakerController._check_and_trigger_restart()
            raise SpeakerError(f"Failed to stop: {e}") from e

    @with_login_retry
    async def set_volume(self, volume: int) -> bool:
        """Set speaker volume (1-100)."""
        try:
            await self.auth.ensure_login()
            volume = max(1, min(100, volume))
            ret = await self.auth.mina_service.player_set_volume(self.device_id, volume)
            log.info(f"player_set_volume device_id={self.device_id} volume={volume} ret={ret}")
            
            self._last_volume = volume
            SpeakerController._consecutive_login_failures = 0
            return True
        except Exception as e:
            log.error(f"set_volume failed: {e}")
            SpeakerController._consecutive_login_failures += 1
            SpeakerController._check_and_trigger_restart()
            raise SpeakerError(f"Failed to set volume: {e}") from e

    @with_login_retry
    async def get_volume(self) -> int:
        """Get current speaker volume."""
        try:
            await self.auth.ensure_login()
            status = await self.auth.mina_service.player_get_status(self.device_id)
            if status and isinstance(status, dict):
                volume = status.get("volume", self._last_volume)
                self._last_volume = volume
                return volume
            return self._last_volume
        except Exception as e:
            log.error(f"get_volume failed: {e}")
            return self._last_volume

    @with_login_retry
    async def get_status(self) -> int:
        """Get speaker playback status.
        
        Returns:
            SpeakerStatus constant (STOPPED=0, PLAYING=1, PAUSED=2)
        
        Raises:
            Exception on transient/network errors. Callers (health check,
            AirPlay poller) already catch and skip the round, so a real
            speaker STOPPED is never confused with a network hiccup.
        """
        await self.auth.ensure_login()
        status = await self.auth.mina_service.player_get_status(self.device_id)
        if status and isinstance(status, dict):
            return status.get("status", SpeakerStatus.STOPPED)
        # Unexpected response shape (None / non-dict) — treat as error
        # rather than silently returning STOPPED, which previously caused
        # the health check to misread transient API failures as a real
        # speaker stop and trigger ghost-pause / position-rewind cascades.
        raise RuntimeError(f"Unexpected player_get_status response: {status!r}")

    @with_login_retry
    async def get_current_track(self) -> Optional[str]:
        """Get currently playing track URL."""
        try:
            await self.auth.ensure_login()
            status = await self.auth.mina_service.player_get_status(self.device_id)
            if status and isinstance(status, dict):
                return status.get("current_song_url")
            return None
        except Exception as e:
            log.error(f"get_current_track failed: {e}")
            return None
