"""DLNA 渲染器状态机"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Callable

from miairx.const import (
    TRANSPORT_STATE_NO_MEDIA,
    TRANSPORT_STATE_PAUSED,
    TRANSPORT_STATE_PLAYING,
    TRANSPORT_STATE_STOPPED,
    TRANSPORT_STATE_TRANSITIONING,
    TRANSPORT_STATUS_OK,
)
from miairx.speaker.controller import SpeakerController

log = logging.getLogger("miairx.protocols.dlna.renderer")


class TransportState:
    NO_MEDIA = TRANSPORT_STATE_NO_MEDIA
    PLAYING = TRANSPORT_STATE_PLAYING
    PAUSED = TRANSPORT_STATE_PAUSED
    STOPPED = TRANSPORT_STATE_STOPPED
    TRANSITIONING = TRANSPORT_STATE_TRANSITIONING


class DlnaRenderer:
    """每个音箱对应一个 DLNA 渲染器实例，管理传输状态"""

    def __init__(self, udn: str, friendly_name: str, speaker: SpeakerController, default_volume: int = 30, config=None):
        self.udn = udn
        self.friendly_name = friendly_name
        self.speaker = speaker
        self.config = config
        self.did = speaker.did
        self._lock = asyncio.Lock()

        self.transport_state = TRANSPORT_STATE_NO_MEDIA
        self.transport_status = TRANSPORT_STATUS_OK
        self.current_uri = ""
        self.current_uri_metadata = ""
        self.play_speed = "1"

        self.volume = default_volume
        self.mute = False
        self._pre_mute_volume = default_volume

        self.event_manager = None
        self.proxy_url_func = None
        self.seek_url_func = None
        self.pre_buffer_func = None
        self.abort_proxy_func: Callable[[str], None] | None = None
        self.resume_proxy_func: Callable[[str], None] | None = None

        self._play_start_time: float = 0.0
        self._accumulated_time: float = 0.0
        self._track_duration: float = 0.0

        self.next_uri: str = ""
        self.next_uri_metadata: str = ""

        self._play_check_task: asyncio.Task | None = None
        self._play_grace_until: float = 0.0
        self._user_stopped: bool = False
        self._last_control_time: float = 0.0
        self._stuck_paused_since: float = 0.0
        self._volume_initialized: bool = False

    VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v', '.3gp', '.ts', '.mts', '.m2ts'}

    def _is_video_uri(self, uri: str) -> bool:
        uri_lower = uri.lower()
        for ext in self.VIDEO_EXTENSIONS:
            if uri_lower.endswith(ext) or f"{ext}?" in uri_lower or f"{ext}&" in uri_lower:
                return True
        if 'video/' in uri_lower:
            return True
        return False

    def _needs_transcode(self) -> bool:
        if not self.speaker:
            return False
        speaker_cfg = getattr(self.speaker, 'speaker', None)
        if not speaker_cfg:
            return False
        return getattr(speaker_cfg, 'hardware', '') in (
            getattr(speaker_cfg, '_NON_LOSSLESS_HARDWARE', set())
        )

    async def set_av_transport_uri(self, uri: str, metadata: str = "") -> bool:
        if self._is_video_uri(uri):
            log.warning(f"[{self.friendly_name}] 拒绝视频文件: {uri[:80]}...")
            return False

        async with self._lock:
            self.current_uri = uri
            self.current_uri_metadata = metadata
            self.transport_state = TRANSPORT_STATE_STOPPED
            self._play_start_time = 0.0
            self._accumulated_time = 0.0
            self._track_duration = self._parse_duration_from_metadata(metadata)
            log.info(f"[{self.friendly_name}] SetAVTransportURI: {uri}")
        if self.pre_buffer_func:
            self.pre_buffer_func(uri)
        await self.notify_state_change()
        return True

    async def _check_play_status(self):
        near_end_count = 0
        while True:
            await asyncio.sleep(1)
            async with self._lock:
                if self.transport_state != TRANSPORT_STATE_PLAYING:
                    break

                current_position = self._get_elapsed_time()

                if self._track_duration > 0 and (self._track_duration - current_position) < 1.0:
                    near_end_count += 1
                    if near_end_count >= 2:
                        log.info(f"[{self.friendly_name}] 歌曲即将结束，剩余 {self._track_duration - current_position:.1f} 秒")
                        asyncio.get_running_loop().create_task(self.next_track())
                        break
                else:
                    near_end_count = 0

    async def play(self) -> bool:
        if self.resume_proxy_func:
            self.resume_proxy_func(self.udn)

        needs_transcode = self._needs_transcode()
        play_url = None

        async with self._lock:
            if not self.current_uri:
                log.warning(f"[{self.friendly_name}] Play 但没有设置 URI")
                return False
            if not self.speaker:
                log.error(f"[{self.friendly_name}] 无可用 speaker 控制器")
                return False

            if self._play_check_task:
                self._play_check_task.cancel()
                self._play_check_task = None

            self.transport_state = TRANSPORT_STATE_TRANSITIONING
            self._user_stopped = False
            self._stuck_paused_since = 0.0
            log.info(f"[{self.friendly_name}] Play: {self.current_uri}")

            resume_position = self._accumulated_time
            if self._play_start_time > 0:
                resume_position += time.time() - self._play_start_time

            play_url = self.current_uri
            if self.proxy_url_func:
                play_url = self.proxy_url_func(self.current_uri, self.udn)
                log.info(f"[{self.friendly_name}] 代理 URL: {play_url}")

            if resume_position > 0 and self.seek_url_func:
                log.info(f"[{self.friendly_name}] 从 {self._format_time(resume_position)} 继续播放")
                track_duration = self._track_duration if self._track_duration > 0 else 3600.0
                seek_url = await self.seek_url_func(
                    self.current_uri, resume_position, track_duration, self.udn
                )
                if seek_url:
                    play_url = seek_url
                    log.info(f"[{self.friendly_name}] Seek URL: {play_url}")

            if needs_transcode:
                self.transport_state = TRANSPORT_STATE_PLAYING
                self._play_grace_until = time.time() + 8.0
                log.info(f"[{self.friendly_name}] 转码模式: 先返回 PLAYING 状态")

        if needs_transcode:
            await self.notify_state_change()

        async with self._lock:
            success = await self.speaker.play_url(play_url)
            if success:
                self.transport_state = TRANSPORT_STATE_PLAYING
                self._play_start_time = time.time()
                if not needs_transcode:
                    self._play_grace_until = time.time() + 8.0
                log.info(f"[{self.friendly_name}] 播放成功")
                self._play_check_task = asyncio.create_task(self._check_play_status())
                asyncio.create_task(self._apply_default_volume())
            else:
                self.transport_state = TRANSPORT_STATE_STOPPED
                self._play_grace_until = 0.0
                log.error(f"[{self.friendly_name}] 播放失败")
        await self.notify_state_change()
        return success

    async def _apply_default_volume(self):
        try:
            if getattr(self.config, 'follow_device_volume', False):
                return
            if self._volume_initialized:
                return
            default_vol = getattr(self.config, 'default_volume', 30)
            if default_vol <= 0:
                return
            await asyncio.sleep(0.5)
            if self.speaker:
                await self.speaker.set_volume(default_vol)
                self.volume = default_vol
                self._volume_initialized = True
                log.info(f"[{self.friendly_name}] 已应用默认音量: {default_vol}%")
                await self.notify_state_change()
        except Exception as e:
            log.error(f"[{self.friendly_name}] 应用默认音量失败: {e}")

    async def pause(self) -> bool:
        if self.abort_proxy_func:
            self.abort_proxy_func(self.udn)

        async with self._lock:
            if not self.speaker:
                self.transport_state = TRANSPORT_STATE_PAUSED
                return True
            success = await self.speaker.pause()
            if success:
                if self._play_start_time > 0:
                    self._accumulated_time += time.time() - self._play_start_time
                    self._play_start_time = 0.0
                self.transport_state = TRANSPORT_STATE_PAUSED
                self._user_stopped = True
                self._stuck_paused_since = time.time()
                if self._play_check_task:
                    self._play_check_task.cancel()
                    self._play_check_task = None
                log.info(f"[{self.friendly_name}] 已暂停")
        await self.notify_state_change()
        return success

    async def stop(self) -> bool:
        if self.abort_proxy_func:
            self.abort_proxy_func(self.udn)
        if self.resume_proxy_func:
            self.resume_proxy_func(self.udn)

        async with self._lock:
            if not self.speaker:
                self.transport_state = TRANSPORT_STATE_STOPPED
                return True
            success = await self.speaker.stop()
            if success:
                self.transport_state = TRANSPORT_STATE_STOPPED
                self._accumulated_time = 0.0
                self._play_start_time = 0.0
                self._user_stopped = True
                if self._play_check_task:
                    self._play_check_task.cancel()
                    self._play_check_task = None
                log.info(f"[{self.friendly_name}] 已停止")
        await self.notify_state_change()
        return success

    async def reset_to_idle(self):
        async with self._lock:
            if self.transport_state == TRANSPORT_STATE_NO_MEDIA:
                return
            old_state = self.transport_state
            self.transport_state = TRANSPORT_STATE_NO_MEDIA
            self.current_uri = ""
            self.current_uri_metadata = ""
            self.next_uri = ""
            self.next_uri_metadata = ""
            self._accumulated_time = 0.0
            self._play_start_time = 0.0
            self._track_duration = 0.0
            self._user_stopped = False
            self._stuck_paused_since = 0.0
            self._volume_initialized = False
            if self._play_check_task:
                self._play_check_task.cancel()
                self._play_check_task = None
            log.info(f"[{self.friendly_name}] 控制端断开，重置为空闲 ({old_state})")
        await self.notify_state_change()

    async def seek(self, unit: str, target: str) -> bool:
        if unit == "REL_TIME":
            seconds = self._parse_time(target)

            seek_url = None
            current_uri = None
            duration = 0.0
            if self.seek_url_func and self.speaker and self.current_uri:
                async with self._lock:
                    duration = self._track_duration
                    current_uri = self.current_uri
                if duration > 0 and current_uri:
                    seek_url = await self.seek_url_func(
                        current_uri, seconds, duration, self.udn
                    )

            async with self._lock:
                if seek_url:
                    log.info(
                        f"[{self.friendly_name}] Seek to {target} "
                        f"({seconds:.1f}s/{self._track_duration:.1f}s)"
                    )

                    was_playing = self.transport_state == TRANSPORT_STATE_PLAYING
                    was_paused = self.transport_state == TRANSPORT_STATE_PAUSED

                    self.transport_state = TRANSPORT_STATE_TRANSITIONING

                    if was_playing:
                        await self.speaker.stop()

                    success = await self.speaker.play_url(seek_url)
                    if success:
                        self._accumulated_time = seconds

                        if was_paused:
                            await self.speaker.pause()
                            self._play_start_time = 0.0
                            self.transport_state = TRANSPORT_STATE_PAUSED
                            log.info(f"[{self.friendly_name}] Seek 成功（保持暂停）")
                        else:
                            self._play_start_time = time.time()
                            self.transport_state = TRANSPORT_STATE_PLAYING
                            log.info(f"[{self.friendly_name}] Seek 成功")
                    else:
                        self.transport_state = TRANSPORT_STATE_STOPPED
                        log.error(f"[{self.friendly_name}] Seek 播放失败")
                    asyncio.get_running_loop().create_task(self.notify_state_change())
                    return success

                self._accumulated_time = seconds
                if self.transport_state == TRANSPORT_STATE_PLAYING:
                    self._play_start_time = time.time()
                log.info(f"[{self.friendly_name}] Seek to {target} (soft)")
                return True
        elif unit == "TRACK_NR":
            log.info(f"[{self.friendly_name}] Seek TRACK_NR={target} (ignored)")
            return True
        return False

    async def next_track(self):
        if self.next_uri:
            if self.abort_proxy_func:
                self.abort_proxy_func(self.udn)
            if self.speaker:
                await self.speaker.stop()
                log.info(f"[{self.friendly_name}] 已停止当前播放，准备切换到下一曲")
                await asyncio.sleep(1.0)

            self.current_uri = self.next_uri
            self.current_uri_metadata = self.next_uri_metadata
            self.next_uri = ""
            self.next_uri_metadata = ""
            self._accumulated_time = 0.0
            self._track_duration = self._parse_duration_from_metadata(
                self.current_uri_metadata
            )

            if self.speaker:
                play_url = self.current_uri
                if self.proxy_url_func:
                    play_url = self.proxy_url_func(self.current_uri, self.udn)
                async with self._lock:
                    self.transport_state = TRANSPORT_STATE_TRANSITIONING
                success = await self.speaker.play_url(play_url)
                async with self._lock:
                    if success:
                        self.transport_state = TRANSPORT_STATE_PLAYING
                        self._play_start_time = time.time()
                        if self._play_check_task:
                            self._play_check_task.cancel()
                            self._play_check_task = None
                        self._play_check_task = asyncio.create_task(self._check_play_status())
                    else:
                        self.transport_state = TRANSPORT_STATE_STOPPED
        else:
            if self.speaker:
                await self.speaker.stop()
                log.info(f"[{self.friendly_name}] 已停止当前播放，模拟自然播完")
                await asyncio.sleep(0.5)

            async with self._lock:
                if self._track_duration > 0:
                    self._accumulated_time = self._track_duration
                self._play_start_time = 0.0
                self.transport_state = TRANSPORT_STATE_STOPPED
                if self._play_check_task:
                    self._play_check_task.cancel()
                    self._play_check_task = None
            log.info(
                f"[{self.friendly_name}] 切歌: 无 next_uri，"
                f"模拟自然播完 (位置={self._format_time(self._accumulated_time)})"
            )
        await self.notify_state_change()

    async def previous_track(self):
        async with self._lock:
            self._accumulated_time = 0.0
            self._play_start_time = time.time()
        if self.speaker and self.current_uri:
            play_url = self.current_uri
            if self.proxy_url_func:
                play_url = self.proxy_url_func(self.current_uri, self.udn)
            await self.speaker.play_url(play_url)
        await self.notify_state_change()

    async def set_next_av_transport_uri(self, uri: str, metadata: str = ""):
        self.next_uri = uri
        self.next_uri_metadata = metadata
        log.info(f"[{self.friendly_name}] SetNextAVTransportURI: {uri}")

    def get_current_transport_actions(self) -> str:
        if self.transport_state == TRANSPORT_STATE_PLAYING:
            return "Pause,Stop,Seek,Next"
        elif self.transport_state == TRANSPORT_STATE_PAUSED:
            return "Play,Stop,Seek,Next"
        elif self.transport_state == TRANSPORT_STATE_STOPPED:
            return "Play,Seek"
        elif self.transport_state == TRANSPORT_STATE_NO_MEDIA:
            return ""
        return "Play,Pause,Stop,Seek,Next"

    def get_transport_info(self) -> dict:
        return {
            "CurrentTransportState": self.transport_state,
            "CurrentTransportStatus": self.transport_status,
            "CurrentSpeed": self.play_speed,
        }

    def get_position_info(self) -> dict:
        rel_time = self._get_elapsed_time()
        duration = self._track_duration

        return {
            "Track": "1" if self.current_uri else "0",
            "TrackDuration": self._format_time(duration),
            "TrackMetaData": self.current_uri_metadata,
            "TrackURI": self.current_uri,
            "RelTime": self._format_time(rel_time),
            "AbsTime": self._format_time(rel_time),
            "RelCount": "0",
            "AbsCount": "0",
        }

    def get_media_info(self) -> dict:
        return {
            "NrTracks": "1" if self.current_uri else "0",
            "MediaDuration": self._format_time(self._track_duration),
            "CurrentURI": self.current_uri,
            "CurrentURIMetaData": self.current_uri_metadata,
            "NextURI": self.next_uri,
            "NextURIMetaData": self.next_uri_metadata,
            "PlayMedium": "NETWORK",
            "RecordMedium": "NOT_IMPLEMENTED",
            "WriteStatus": "NOT_IMPLEMENTED",
        }

    def get_transport_settings(self) -> dict:
        return {
            "PlayMode": "NORMAL",
            "RecQualityMode": "NOT_IMPLEMENTED",
        }

    async def set_volume(self, volume: int) -> bool:
        volume = max(0, min(100, volume))
        if not self.speaker:
            self.volume = volume
            return True
        success = await self.speaker.set_volume(volume)
        if success:
            self.volume = volume
            if volume > 0:
                self.mute = False
        return success

    async def get_volume(self) -> int:
        if not self.speaker:
            return self.volume
        vol = await self.speaker.get_volume()
        self.volume = vol
        return vol

    async def set_mute(self, mute: bool) -> bool:
        if mute and not self.mute:
            self._pre_mute_volume = self.volume
            if self.speaker:
                success = await self.speaker.set_volume(0)
            else:
                success = True
        elif not mute and self.mute:
            if self.speaker:
                success = await self.speaker.set_volume(self._pre_mute_volume)
            else:
                success = True
        else:
            success = True
        if success:
            self.mute = mute
        return success

    def get_mute(self) -> bool:
        return self.mute

    async def notify_state_change(self):
        if not self.event_manager:
            return
        try:
            await self.event_manager.notify(self)
        except Exception as e:
            log.error(f"[{self.friendly_name}] 事件通知失败: {e}")

    def _get_elapsed_time(self) -> float:
        if self.transport_state == TRANSPORT_STATE_PLAYING and self._play_start_time > 0:
            return self._accumulated_time + (time.time() - self._play_start_time)
        return self._accumulated_time

    @staticmethod
    def _format_time(seconds: float) -> str:
        if seconds <= 0:
            return "00:00:00"
        total = int(seconds)
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    @staticmethod
    def _parse_time(time_str: str) -> float:
        try:
            parts = time_str.split(":")
            if len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + float(s)
            elif len(parts) == 2:
                m, s = parts
                return int(m) * 60 + float(s)
        except (ValueError, IndexError):
            pass
        return 0.0

    @staticmethod
    def _parse_duration_from_metadata(metadata: str) -> float:
        if not metadata:
            return 0.0
        try:
            match = re.search(r'duration="([^"]+)"', metadata)
            if match:
                duration_str = match.group(1)
                if "." in duration_str:
                    duration_str = duration_str.split(".")[0]
                return DlnaRenderer._parse_time(duration_str)

            root = ET.fromstring(metadata)
            for elem in root.iter():
                duration = elem.get("duration")
                if duration:
                    if "." in duration:
                        duration = duration.split(".")[0]
                    return DlnaRenderer._parse_time(duration)
        except Exception:
            pass
        return 0.0
