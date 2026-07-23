"""Main application orchestrator for MiAirX"""

import asyncio
import logging
import time
from typing import Optional

import aiohttp
from aiohttp import web
from zeroconf import Zeroconf, IPVersion

from miairx.auth.manager import AuthManager
from miairx.config.models import AppConfig
from miairx.config.store import ConfigStore
from miairx.const import (
    TRANSPORT_STATE_PAUSED,
    TRANSPORT_STATE_PLAYING,
    TRANSPORT_STATE_STOPPED,
    TRANSPORT_STATE_TRANSITIONING,
)
from miairx.core.lifecycle import lifecycle
from miairx.media.proxy import MediaProxy
from miairx.protocols.airplay.speaker_airplay import SpeakerAirplay
from miairx.protocols.dlna.renderer import DlnaRenderer
from miairx.protocols.dlna.server import DlnaHttpServer
from miairx.protocols.dlna.ssdp import SsdpServer
from miairx.speaker.controller import SpeakerController
from miairx.speaker.manager import SpeakerManager
from miairx.web.app import create_web_app

log = logging.getLogger(__name__)

_STATUS_MAP = {
    0: TRANSPORT_STATE_STOPPED,
    1: TRANSPORT_STATE_PLAYING,
    2: TRANSPORT_STATE_PAUSED,
}


async def _poll_one_renderer(app, udn: str, renderer: DlnaRenderer) -> None:
    """Poll a single renderer's speaker state (for use with asyncio.gather).

    Extracted so all renderers are polled concurrently instead of serially.
    """
    if not renderer.speaker:
        return

    # Idle detection: controller disconnected while renderer is stuck
    idle = False
    if (
        renderer.current_uri
        and renderer.transport_state == TRANSPORT_STATE_PAUSED
        and renderer._stuck_paused_since > 0
        and (time.time() - renderer._stuck_paused_since) > 30
    ):
        if not renderer._user_stopped:
            idle = True
        elif (
            renderer.event_manager
            and not renderer.event_manager.has_subscribers()
        ):
            idle = True
    elif (
        renderer.current_uri
        and renderer.transport_state == TRANSPORT_STATE_STOPPED
        and renderer._last_control_time > 0
        and (time.time() - renderer._last_control_time) > 60
        and renderer.event_manager
        and not renderer.event_manager.has_subscribers()
    ):
        idle = True

    if idle:
        await renderer.reset_to_idle()
        renderer._stuck_paused_since = 0.0
        return

    if not renderer.current_uri:
        return

    try:
        speaker_status = await asyncio.wait_for(
            renderer.speaker.get_status(), timeout=10
        )
    except Exception as e:
        log.warning(f"[{renderer.friendly_name}] Poll failed: {e}")
        return

    new_state = _STATUS_MAP.get(speaker_status, TRANSPORT_STATE_STOPPED)
    if renderer.transport_state == new_state:
        return

    old_state = renderer.transport_state
    if old_state == TRANSPORT_STATE_TRANSITIONING:
        return
    if (
        renderer._play_grace_until > 0
        and time.time() < renderer._play_grace_until
        and old_state == TRANSPORT_STATE_PLAYING
        and new_state != TRANSPORT_STATE_PLAYING
    ):
        return
    if (
        new_state == TRANSPORT_STATE_STOPPED
        and old_state == TRANSPORT_STATE_PLAYING
        and renderer.proxy_url_func
        and renderer.current_uri
        and not renderer._user_stopped
    ):
        return
    if old_state == TRANSPORT_STATE_PAUSED and new_state == TRANSPORT_STATE_PLAYING:
        if renderer._user_stopped:
            return

    renderer.transport_state = new_state
    log_msg = app._handle_state_transition(udn, renderer, old_state, new_state)

    if not (new_state == TRANSPORT_STATE_STOPPED and not renderer._user_stopped):
        await renderer.notify_state_change()
    log.info(f"[{renderer.friendly_name}] State sync: {log_msg}")


class Application:
    """MiAirX application root - wires all components together."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.config_store = ConfigStore(config.conf_path)
        self.session: Optional[aiohttp.ClientSession] = None
        self.auth: Optional[AuthManager] = None
        self.speaker_manager: Optional[SpeakerManager] = None
        
        # DLNA components
        self.ssdp: Optional[SsdpServer] = None
        self.dlna_server: Optional[DlnaHttpServer] = None
        self.media_proxy: Optional[MediaProxy] = None
        self._resume_tasks: dict = {}
        self.renderers: dict[str, DlnaRenderer] = {}  # udn -> renderer
        self._did_to_udn: dict[str, str] = {}  # did -> udn
        
        # AirPlay components
        self._zeroconf: Optional[Zeroconf] = None
        self._airplay_services: dict[str, SpeakerAirplay] = {}  # did -> SpeakerAirplay
        
        # Web management
        self.web_runner: Optional[web.AppRunner] = None
        self.web_app: Optional[web.Application] = None
        
        self._is_running = False

    async def start(self) -> None:
        """Start the application."""
        log.warning("Starting MiAirX application...")
        
        # Create shared HTTP session
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)
        )
        
        # Initialize authentication
        self.auth = AuthManager(self.config, self.session)
        
        # Initialize speaker manager
        self.speaker_manager = SpeakerManager(self.config, self.auth)
        await self.speaker_manager.initialize()
        
        # Register shutdown callback
        lifecycle.register_shutdown_callback(self.stop)
        
        # Start DLNA server
        await self._start_dlna_server()
        
        # Start AirPlay server
        await self._start_airplay_server()
        
        # Start web management interface
        await self._start_web_server()
        
        self._is_running = True
        
        # Show startup summary
        self._show_startup_summary()
        
        # Start periodic tasks
        asyncio.create_task(self._periodic_health_check())

    def _show_startup_summary(self) -> None:
        """Show startup summary with configuration status."""
        print("\n" + "=" * 60)
        print("MiAirX 启动成功!")
        print("=" * 60)
        
        # Show configuration status
        if not self.config.account and not self.config.cookie:
            print("\n⚠️  未配置小米账号")
            print("   请通过以下方式配置:")
            print(f"   1. Web 界面: http://{self.config.hostname}:{self.config.web_port}")
            print(f"   2. 配置文件: {self.config.conf_path}/config.json")
        else:
            print(f"\n✅ 小米账号: {self.config.account[:3]}***")
        
        # Show speakers
        speakers = self.config.get_enabled_speakers()
        if speakers:
            print(f"\n🔊 音箱数量: {len(speakers)}")
            for speaker in speakers:
                print(f"   - {speaker.get_dlna_name()} (DID: {speaker.did})")
        else:
            print("\n⚠️  未配置音箱")
            print("   请在配置文件中设置 mi_did 或通过 Web 界面配置")
        
        # Show server addresses
        print(f"\n📡 服务地址:")
        print(f"   DLNA: http://{self.config.hostname}:{self.config.dlna_port}")
        print(f"   Web:  http://{self.config.hostname}:{self.config.web_port}")
        
        print("\n" + "=" * 60)
        print("按 Ctrl+C 停止服务")
        print("=" * 60 + "\n")

    async def _start_dlna_server(self) -> None:
        """Start DLNA server components."""
        log.info("Starting DLNA server...")
        
        # Create SSDP server
        self.ssdp = SsdpServer(self.config.hostname, self.config.dlna_port)
        
        # Create DLNA HTTP server
        self.dlna_server = DlnaHttpServer(
            self.config.hostname,
            self.config.dlna_port,
            self.config,
        )
        
        # Create media proxy
        self.media_proxy = MediaProxy(self.config.hostname, self.config.dlna_port)
        
        # Create renderers for each enabled speaker
        for speaker in self.config.get_enabled_speakers():
            controller = self.speaker_manager.get_controller_by_did(speaker.did)
            if controller:
                renderer = DlnaRenderer(
                    udn=speaker.udn,
                    friendly_name=speaker.get_dlna_name(),
                    speaker=controller,
                    default_volume=self.config.default_volume,
                    config=self.config,
                )
                
                # Register with SSDP and DLNA server
                self.ssdp.register_renderer(speaker.udn, speaker.get_dlna_name())
                self.dlna_server.register_renderer(renderer)
                
                # Store renderer
                self.renderers[speaker.udn] = renderer
                self._did_to_udn[speaker.did] = speaker.udn
                
                log.info(f"Registered renderer: {speaker.get_dlna_name()} (udn={speaker.udn})")
        
        # Start servers (even if no renderers registered)
        await self.dlna_server.start()
        await self.ssdp.start()
        
        if not self.renderers:
            log.warning("No speakers registered. DLNA server started but no devices to advertise.")
            log.warning("Please configure speakers in Web UI or config file.")
        
        log.warning(f"DLNA server started on {self.config.hostname}:{self.config.dlna_port}")

    async def _start_airplay_server(self) -> None:
        """Start AirPlay server components."""
        log.info("Starting AirPlay server...")
        
        # Create shared Zeroconf instance
        self._zeroconf = Zeroconf(ip_version=IPVersion.All)
        
        # Create AirPlay service for each enabled speaker
        for speaker in self.config.get_enabled_speakers():
            controller = self.speaker_manager.get_controller_by_did(speaker.did)
            if controller:
                airplay = SpeakerAirplay(
                    hostname=self.config.hostname,
                    controller=controller,
                    shared_zeroconf=self._zeroconf,
                    config=self.config,
                )
                
                await airplay.start()
                self._airplay_services[speaker.did] = airplay
                
                log.info(f"Registered AirPlay service: {speaker.get_dlna_name()}")
        
        log.info(f"AirPlay server started")

    async def _start_web_server(self) -> None:
        """Start web management interface."""
        log.info("Starting web management interface...")
        
        # Create web application
        self.web_app = create_web_app(self.config, self, self.config_store)
        
        # Create web runner
        self.web_runner = web.AppRunner(self.web_app, access_log=None)
        await self.web_runner.setup()
        
        # Start web server
        site = web.TCPSite(self.web_runner, self.config.hostname, self.config.web_port)
        await site.start()
        
        log.warning(f"Web management interface started on http://{self.config.hostname}:{self.config.web_port}")

    async def stop(self) -> None:
        """Stop the application."""
        if not self._is_running:
            return
        
        log.warning("Stopping MiAirX application...")
        self._is_running = False
        
        # Stop web server
        await self._stop_web_server()
        
        # Stop AirPlay server
        await self._stop_airplay_server()
        
        # Stop DLNA server
        await self._stop_dlna_server()
        
        # Stop all speakers
        if self.speaker_manager:
            await self.speaker_manager.stop_all()
        
        # Close authentication
        if self.auth:
            await self.auth.close()
        
        # Close HTTP session
        if self.session:
            await self.session.close()
        
        log.warning("MiAirX application stopped")

    async def _stop_web_server(self) -> None:
        """Stop web management interface."""
        if self.web_runner:
            await self.web_runner.cleanup()
            self.web_runner = None
            self.web_app = None

    async def _stop_dlna_server(self) -> None:
        """Stop DLNA server components."""
        if self.ssdp:
            await self.ssdp.stop()
        
        if self.dlna_server:
            await self.dlna_server.stop()
        
        if self.media_proxy:
            await self.media_proxy.cleanup()

    async def _stop_airplay_server(self) -> None:
        """Stop AirPlay server components (parallel)."""
        async def _stop_one(did: str, airplay) -> None:
            try:
                await asyncio.wait_for(airplay.stop(), timeout=5.0)
            except asyncio.TimeoutError:
                log.warning(f"Timeout stopping AirPlay for {did}")
            except Exception as e:
                log.warning(f"Failed to stop AirPlay for {did}: {e}")

        if self._airplay_services:
            await asyncio.gather(
                *[_stop_one(did, ap) for did, ap in self._airplay_services.items()],
                return_exceptions=True,
            )

        self._airplay_services.clear()
        
        if self._zeroconf:
            try:
                self._zeroconf.close()
            except Exception:
                pass
            self._zeroconf = None

    async def _periodic_health_check(self) -> None:
        """Periodic health check task (matches MiAir logic)."""
        while self._is_running:
            try:
                await self._poll_speaker_states()
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Health check error: {e}")
                await asyncio.sleep(5)

    async def _poll_speaker_states(self) -> None:
        """Poll all speaker states in parallel via asyncio.gather."""
        tasks = [
            _poll_one_renderer(self, udn, renderer)
            for udn, renderer in self.renderers.items()
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _handle_state_transition(self, udn, renderer, old_state, new_state) -> str:
        """Handle side-effects of state transitions (matches MiAir)."""

        if new_state == TRANSPORT_STATE_PAUSED and old_state == TRANSPORT_STATE_PLAYING:
            if renderer._play_start_time > 0:
                renderer._accumulated_time += time.time() - renderer._play_start_time
                renderer._play_start_time = 0.0
            return f"{old_state} -> {new_state}"

        if new_state == TRANSPORT_STATE_PLAYING and old_state == TRANSPORT_STATE_PAUSED:
            # 补偿健康检查假暂停期间冻结的位置：STOPPED→PAUSED 时
            # _play_start_time 被清零，位置冻结在 _accumulated_time；但音箱
            # 实际一直在播，恢复时把假暂停时长（_stuck_paused_since 至今）
            # 补回，避免位置整体落后、以及下次恢复时再次拉回。
            if renderer._stuck_paused_since > 0:
                renderer._accumulated_time += time.time() - renderer._stuck_paused_since
                renderer._stuck_paused_since = 0.0
            renderer._play_start_time = time.time()
            return f"{old_state} -> {new_state}"

        if new_state == TRANSPORT_STATE_STOPPED and old_state in (
            TRANSPORT_STATE_PLAYING, TRANSPORT_STATE_PAUSED
        ):
            if renderer._play_start_time > 0:
                renderer._accumulated_time += time.time() - renderer._play_start_time
            renderer._play_start_time = 0.0
            renderer.transport_state = TRANSPORT_STATE_PAUSED

            if renderer._stuck_paused_since == 0.0:
                renderer._stuck_paused_since = time.time()

            if (
                self.config
                and self.config.auto_resume_on_interrupt
                and not renderer._user_stopped
                and (time.time() - renderer._stuck_paused_since) < 15
            ):
                if udn in self._resume_tasks:
                    self._resume_tasks[udn].cancel()
                delay = self.config.resume_delay_seconds
                self._resume_tasks[udn] = asyncio.create_task(
                    self._auto_resume_after_delay(udn, delay)
                )
                log.info(f"[{renderer.friendly_name}] 将在 {delay} 秒后自动恢复播放")
            return f"{old_state} -> PAUSED (保持位置)"

        if new_state == TRANSPORT_STATE_STOPPED:
            renderer._accumulated_time = 0.0
            renderer._play_start_time = 0.0

        return f"{old_state} -> {new_state}"

    async def _auto_resume_after_delay(self, udn: str, delay: int) -> None:
        """Auto-resume playback after delay (matches MiAir)."""
        try:
            await asyncio.sleep(delay)
            renderer = self.renderers.get(udn)
            if not renderer:
                return

            if renderer.transport_state == TRANSPORT_STATE_PAUSED:
                log.info(f"[{renderer.friendly_name}] 自动恢复播放")
                await renderer.play()

            if udn in self._resume_tasks:
                del self._resume_tasks[udn]
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"自动恢复播放失败: {e}")

    async def restart_dlna(self) -> None:
        """Restart DLNA server."""
        log.info("Restarting DLNA server...")
        await self._stop_dlna_server()
        await self._start_dlna_server()

    async def restart_airplay(self) -> None:
        """Restart AirPlay server."""
        log.info("Restarting AirPlay server...")
        await self._stop_airplay_server()
        await self._start_airplay_server()

    def get_renderer_by_did(self, did: str) -> Optional[DlnaRenderer]:
        """Get DLNA renderer by device DID."""
        udn = self._did_to_udn.get(did)
        if udn:
            return self.renderers.get(udn)
        return None

    def get_renderer_by_udn(self, udn: str) -> Optional[DlnaRenderer]:
        """Get DLNA renderer by UDN."""
        return self.renderers.get(udn)

    async def get_all_devices(self) -> list[dict]:
        """Get all devices from Xiaomi account."""
        if not self.auth:
            return []
        
        if not self.config.account and not self.config.cookie:
            return []
        
        try:
            await self.auth.ensure_login()
            devices = await self.auth.get_device_list()
            return devices or []
        except Exception as e:
            log.error(f"Failed to get device list: {e}")
            return []
