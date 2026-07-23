"""Speaker AirPlay integration for MiAirX"""

import asyncio
import logging
import time
from typing import Optional

from zeroconf import Zeroconf

from miairx.protocols.airplay.server import AirplayServer
from miairx.speaker.controller import SpeakerController

log = logging.getLogger(__name__)


class SpeakerAirplay:
    """AirPlay receiver wrapper for a single Xiaomi speaker.
    
    Creates an independent AirPlay receiver service for each speaker.
    When a phone connects, audio is forwarded directly to the corresponding speaker.
    """

    def __init__(
        self,
        hostname: str,
        controller: SpeakerController,
        shared_zeroconf: Optional[Zeroconf] = None,
        config=None,
    ):
        self.hostname = hostname
        self.controller = controller
        self.speaker = controller.speaker
        self.device_name = self.speaker.get_dlna_name()
        self.shared_zeroconf = shared_zeroconf
        self.config = config
        self.airplay_server: Optional[AirplayServer] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        # AirPlay state
        self._stream_url: str = ""
        self._airplay_active: bool = False
        self._poll_task: Optional[asyncio.Task] = None
        self._play_grace_until: float = 0.0

    async def start(self):
        """Start AirPlay service for this speaker."""
        try:
            self._loop = asyncio.get_running_loop()

            self.airplay_server = AirplayServer(
                hostname=self.hostname,
                device_name=self.device_name,
                shared_zeroconf=self.shared_zeroconf,
                speaker_hardware=self.speaker.hardware,
            )

            # Set callbacks
            self.airplay_server.on_play_start = self._on_play_start
            self.airplay_server.on_play_stop = self._on_play_stop
            self.airplay_server.on_volume_change = self._on_volume_change

            await self.airplay_server.start()
            log.info(f"AirPlay service started for {self.device_name}, port: {self.airplay_server.rtsp_port}")
            
        except Exception as e:
            log.error(f"Failed to start AirPlay for {self.device_name}: {e}")
            raise

    async def stop(self):
        """Stop AirPlay service for this speaker."""
        self._airplay_active = False
        
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        
        if self.airplay_server:
            await self.airplay_server.stop()
            self.airplay_server = None
            log.info(f"AirPlay service stopped for {self.device_name}")

    def _on_play_start(self, stream_url: str):
        """AirPlay play start callback (called from RTSP thread)."""
        log.info(f"AirPlay audio -> {self.device_name}: {stream_url}")
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._play_on_speaker(stream_url), self._loop)
        else:
            log.warning(f"AirPlay: event loop not running, cannot play to {self.device_name}")

    async def _play_on_speaker(self, stream_url: str):
        """Play audio on the speaker."""
        try:
            self._stream_url = stream_url
            self._airplay_active = True
            self._play_grace_until = time.time() + 10.0
            
            success = await self.controller.play_url(stream_url)
            if success:
                log.info(f"AirPlay audio playing on {self.device_name}: {stream_url}")
                self._start_poll()
                
                # Apply default volume
                if self.config:
                    default_vol = getattr(self.config, 'default_volume', 0)
                    follow_dev_vol = getattr(self.config, 'follow_device_volume', False)
                    if default_vol > 0 and not follow_dev_vol:
                        await asyncio.sleep(0.5)
                        await self.controller.set_volume(default_vol)
                        log.info(f"Applied default volume: {default_vol}%")
            else:
                log.error(f"Failed to play AirPlay audio on {self.device_name}")
                
        except Exception as e:
            log.error(f"AirPlay play error: {e}")

    def _on_play_stop(self):
        """AirPlay play stop callback (called from RTSP thread)."""
        log.info(f"AirPlay stopped on {self.device_name}")
        self._airplay_active = False
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._stop_on_speaker(), self._loop)

    async def _stop_on_speaker(self):
        """Stop playback on the speaker."""
        try:
            if self._poll_task:
                self._poll_task.cancel()
                try:
                    await self._poll_task
                except asyncio.CancelledError:
                    pass
                self._poll_task = None
            
            await self.controller.stop()
            log.info(f"Stopped playback on {self.device_name}")
        except Exception as e:
            log.error(f"AirPlay stop error: {e}")

    def _on_volume_change(self, volume_pct: float):
        """AirPlay volume change callback (called from RTSP thread)."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.controller.set_volume(int(volume_pct)),
                self._loop,
            )

    def _start_poll(self):
        """Start polling task for speaker state."""
        if self._poll_task:
            self._poll_task.cancel()
        self._poll_task = asyncio.create_task(self._poll_speaker_state())

    async def _poll_speaker_state(self):
        """Poll speaker state for auto-resume on interrupt."""
        try:
            while self._airplay_active:
                await asyncio.sleep(3)
                
                # Skip during grace period
                if time.time() < self._play_grace_until:
                    continue
                
                try:
                    status = await self.controller.get_status()
                    
                    # Speaker stopped but AirPlay still active
                    if status == 0 and self._airplay_active:
                        log.info(f"Speaker stopped while AirPlay active, attempting resume")
                        await asyncio.sleep(1)
                        success = await self.controller.play_url(self._stream_url)
                        if success:
                            log.info(f"Resumed playback on {self.device_name}")
                            self._play_grace_until = time.time() + 10.0
                            
                except Exception as e:
                    log.warning(f"Poll error for {self.device_name}: {e}")
                    
        except asyncio.CancelledError:
            pass
