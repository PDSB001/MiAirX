"""Small, cached runtime health snapshot shared by Web UI and diagnostics."""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache

from miairx.auth.manager import XIAOMI_STATUS_NORMAL


@lru_cache(maxsize=1)
def ffmpeg_info() -> dict[str, object]:
    """Return FFmpeg availability/version without probing on every poll."""
    executable = shutil.which("ffmpeg")
    if not executable:
        return {"available": False, "version": None}
    version = None
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
        first_line = (result.stdout or result.stderr).splitlines()
        if first_line:
            version = first_line[0].strip()[:200]
    except (OSError, subprocess.SubprocessError):
        pass
    return {"available": True, "version": version}


def _current_source(app, did: str) -> str | None:
    airplay = getattr(app, "_airplay_services", {}).get(did)
    if airplay and getattr(airplay, "_airplay_active", False):
        return "AirPlay"
    renderer = app.get_renderer_by_did(did) if hasattr(app, "get_renderer_by_did") else None
    if renderer and getattr(renderer, "current_uri", ""):
        state = str(getattr(renderer, "transport_state", "")).upper()
        if state in {"PLAYING", "PAUSED_PLAYBACK", "TRANSITIONING"}:
            return "DLNA"
    return None


def build_health_snapshot(app) -> dict[str, object]:
    """Build a deliberately small runtime snapshot from cached state."""
    config = app.config
    configured_speakers = config.get_enabled_speakers()
    cached = getattr(app, "_speaker_health", {})
    speakers = []
    for speaker in configured_speakers:
        state = cached.get(speaker.did, {})
        speakers.append({
            "did": speaker.did,
            "name": speaker.name or speaker.get_dlna_name(),
            "model": speaker.hardware or "unknown",
            "status": state.get("status", "unknown"),
            "current_source": _current_source(app, speaker.did),
        })

    auth = getattr(app, "auth", None)
    xiaomi_status = auth.login_status() if auth else "unknown"
    dlna_running = bool(
        getattr(app, "_is_running", False)
        and getattr(getattr(app, "dlna_server", None), "_site", None)
        and getattr(getattr(app, "ssdp", None), "_transport", None)
    )
    airplay_services = getattr(app, "_airplay_services", {})
    airplay_running = bool(
        getattr(app, "_is_running", False)
        and getattr(app, "_zeroconf", None)
        and len(airplay_services) == len(configured_speakers)
        and all(
            getattr(getattr(service, "airplay_server", None), "_running", False)
            for service in airplay_services.values()
        )
    )
    ffmpeg = ffmpeg_info()
    online_count = sum(item["status"] == "online" for item in speakers)
    overall_ok = bool(
        getattr(app, "_is_running", False)
        and dlna_running
        and airplay_running
        and xiaomi_status == XIAOMI_STATUS_NORMAL
        and online_count == len(speakers)
        and speakers
    )

    return {
        "status": "ok" if overall_ok else "degraded",
        "miairx": {"running": bool(getattr(app, "_is_running", False))},
        "xiaomi": {"status": xiaomi_status},
        "dlna": {"running": dlna_running},
        "airplay": {"running": airplay_running},
        "ffmpeg": ffmpeg,
        "network": {
            "hostname": (
                app.resolve_hostname()
                if hasattr(app, "resolve_hostname")
                else config.hostname
            ),
            "dlna_port": config.dlna_port,
            "web_port": config.web_port,
            "airplay_port_start": config.airplay_port_start,
        },
        "speakers": speakers,
    }
