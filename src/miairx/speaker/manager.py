"""Speaker manager for MiAirX"""

import logging
from typing import Optional

from miairx.auth.manager import AuthManager
from miairx.config.models import AppConfig, SpeakerConfig
from miairx.speaker.controller import SpeakerController

log = logging.getLogger(__name__)


class SpeakerManager:
    """Manages multiple speaker controllers."""

    def __init__(self, config: AppConfig, auth: AuthManager):
        self.config = config
        self.auth = auth
        self._controllers: dict[str, SpeakerController] = {}  # did -> controller

    async def initialize(self) -> None:
        """Initialize speakers from configuration."""
        # Update speaker info from cloud
        try:
            await self.auth.update_speakers_info()
        except Exception as e:
            log.warning(f"Failed to update speakers info: {e}")
            log.warning("Speakers will be initialized without cloud info")
        
        # Create controllers for enabled speakers
        for speaker in self.config.get_enabled_speakers():
            self.get_or_create_controller(speaker)
        
        log.info(f"Initialized {len(self._controllers)} speakers")

    def get_or_create_controller(self, speaker: SpeakerConfig) -> SpeakerController:
        """Get or create a controller for the given speaker."""
        if speaker.did not in self._controllers:
            controller = SpeakerController(speaker, self.auth)
            self._controllers[speaker.did] = controller
            log.info(f"Created controller for speaker {speaker.name} (did={speaker.did})")
        return self._controllers[speaker.did]

    def get_controller_by_did(self, did: str) -> Optional[SpeakerController]:
        """Get controller by device DID."""
        return self._controllers.get(did)

    def get_controller_by_udn(self, udn: str) -> Optional[SpeakerController]:
        """Get controller by UDN."""
        for controller in self._controllers.values():
            if controller.speaker.udn == udn:
                return controller
        return None

    def get_all_controllers(self) -> list[SpeakerController]:
        """Get all speaker controllers."""
        return list(self._controllers.values())

    def get_enabled_controllers(self) -> list[SpeakerController]:
        """Get controllers for enabled speakers."""
        return [
            c for c in self._controllers.values()
            if c.speaker.enabled
        ]

    async def stop_all(self) -> None:
        """Stop all speakers."""
        for controller in self._controllers.values():
            try:
                await controller.stop()
            except Exception as e:
                log.warning(f"Failed to stop speaker {controller.speaker.name}: {e}")

    async def set_volume_all(self, volume: int) -> None:
        """Set volume for all speakers."""
        for controller in self._controllers.values():
            try:
                await controller.set_volume(volume)
            except Exception as e:
                log.warning(f"Failed to set volume for speaker {controller.speaker.name}: {e}")
