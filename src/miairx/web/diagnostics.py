"""Diagnostic bundle generation for MiAirX.

Produces an in-memory zip archive containing everything needed to troubleshoot
a deployment: a redacted copy of the configuration, the live log file, and a
JSON snapshot of runtime state (version, platform, speakers). Sensitive fields
(account, password, cookie, web password) are masked before serialisation.
"""

import io
import json
import logging
import platform
import sys
import zipfile
from datetime import datetime, timezone

from miairx import __version__

log = logging.getLogger(__name__)

_SENSITIVE_KEYS = {"password", "cookie", "web_password"}
_MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB tail of the log file


def redact_config(config) -> dict:
    """Return a redacted copy of the app config as a plain dict."""
    data = config.model_dump()
    # Mask the account to the first 3 characters to preserve a diagnostic hint.
    if data.get("account"):
        data["account"] = data["account"][:3] + "***"
    for key in _SENSITIVE_KEYS:
        if data.get(key):
            data[key] = "***"
    return data


def _runtime_snapshot(app) -> dict:
    speakers = []
    for speaker in app.config.get_enabled_speakers():
        speakers.append({
            "did": speaker.did,
            "name": speaker.name,
            "hardware": speaker.hardware,
            "device_id": speaker.device_id,
            "udn": speaker.udn,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "miairx_version": __version__,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "hostname": app.config.hostname,
        "dlna_port": app.config.dlna_port,
        "web_port": app.config.web_port,
        "airplay_port_start": app.config.airplay_port_start,
        "is_running": app._is_running,
        "is_logged_in": bool(app.auth and app.auth.is_logged_in()),
        "speakers": speakers,
    }


def _log_file_tail(path: str) -> bytes:
    """Read up to the last ``_MAX_LOG_BYTES`` of a log file."""
    try:
        with open(path, "rb") as f:
            f.seek(0, io.SEEK_END)
            size = f.tell()
            start = max(0, size - _MAX_LOG_BYTES)
            f.seek(start)
            return f.read()
    except OSError as exc:
        log.debug("Could not read log file %s: %s", path, exc)
        return b""


def build_diagnostics_bundle(app) -> io.BytesIO:
    """Build and return an in-memory zip archive of diagnostics data."""
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        # Redacted configuration.
        archive.writestr(
            "config.json",
            json.dumps(redact_config(app.config), ensure_ascii=False, indent=2),
        )
        # Runtime snapshot.
        archive.writestr(
            "system-info.json",
            json.dumps(_runtime_snapshot(app), ensure_ascii=False, indent=2),
        )
        # Log tail.
        log_tail = _log_file_tail(app.config.log_file)
        if log_tail:
            archive.writestr("miair.log", log_tail)

    buffer.seek(0)
    return buffer
