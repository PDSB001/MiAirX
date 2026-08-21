"""Stable playback error codes for the API and management console."""

from __future__ import annotations

from enum import StrEnum

from miairx.auth.errors import LoginError, TokenExpiredError


class PlaybackErrorCode(StrEnum):
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SPEAKER_UNAVAILABLE = "SPEAKER_UNAVAILABLE"
    XIAOMI_AUTH_EXPIRED = "XIAOMI_AUTH_EXPIRED"
    MINA_REQUEST_FAILED = "MINA_REQUEST_FAILED"
    TRANSCODE_FAILED = "TRANSCODE_FAILED"
    UNSUPPORTED_MEDIA = "UNSUPPORTED_MEDIA"
    NETWORK_CONFIGURATION_ERROR = "NETWORK_CONFIGURATION_ERROR"


PLAYBACK_ERROR_MESSAGES = {
    PlaybackErrorCode.SOURCE_UNAVAILABLE: "音频来源无法访问，请检查链接是否仍然有效。",
    PlaybackErrorCode.SPEAKER_UNAVAILABLE: "音箱当前不可用，请确认设备在线后重试。",
    PlaybackErrorCode.XIAOMI_AUTH_EXPIRED: "小米登录已失效，请重新扫码登录。",
    PlaybackErrorCode.MINA_REQUEST_FAILED: "小米音箱服务请求失败，请稍后重试。",
    PlaybackErrorCode.TRANSCODE_FAILED: "音频转换失败，请检查 FFmpeg 或更换音频格式。",
    PlaybackErrorCode.UNSUPPORTED_MEDIA: "不支持此媒体地址或音频格式。",
    PlaybackErrorCode.NETWORK_CONFIGURATION_ERROR: "网络地址配置有误，音箱无法访问该来源。",
}


def classify_playback_exception(error: Exception) -> PlaybackErrorCode:
    """Best-effort mapping for errors raised by MiNA/media implementations."""
    message = str(error).lower()
    if isinstance(error, (LoginError, TokenExpiredError)) or any(
        marker in message
        for marker in ("token expired", "unauthorized", "servicetoken", "login failed", "401")
    ):
        return PlaybackErrorCode.XIAOMI_AUTH_EXPIRED
    if any(marker in message for marker in ("ffmpeg", "transcod", "convert audio")):
        return PlaybackErrorCode.TRANSCODE_FAILED
    if any(marker in message for marker in ("unsupported", "codec", "media format", "content-type")):
        return PlaybackErrorCode.UNSUPPORTED_MEDIA
    if any(marker in message for marker in ("localhost", "127.0.0.1", "network configuration")):
        return PlaybackErrorCode.NETWORK_CONFIGURATION_ERROR
    if any(marker in message for marker in ("source", "download", "http 404", "http 403", "url unavailable")):
        return PlaybackErrorCode.SOURCE_UNAVAILABLE
    if any(marker in message for marker in ("offline", "not online", "speaker unavailable", "device unavailable")):
        return PlaybackErrorCode.SPEAKER_UNAVAILABLE
    return PlaybackErrorCode.MINA_REQUEST_FAILED
