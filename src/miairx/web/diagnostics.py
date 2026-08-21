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
import re
import sys
import zipfile
from datetime import datetime, timezone

from miairx import __version__
from miairx.core.health import build_health_snapshot

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
    health = build_health_snapshot(app)
    speakers = [
        {
            "name": speaker["name"],
            "model": speaker["model"],
            "status": speaker["status"],
            "current_source": speaker["current_source"],
        }
        for speaker in health["speakers"]
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "miairx_version": __version__,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "ffmpeg": health["ffmpeg"],
        "xiaomi": health["xiaomi"],
        "dlna": health["dlna"],
        "airplay": health["airplay"],
        "network": health["network"],
        "miairx": health["miairx"],
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


def _redact_log_tail(raw: bytes, config) -> bytes:
    """Remove configured secrets and common credential fields from logs."""
    text = raw.decode("utf-8", errors="replace")
    for secret in (config.password, config.cookie, config.web_password):
        if secret:
            text = text.replace(secret, "***")
    text = re.sub(
        r"(?im)(authorization|cookie)(\s*:\s*)[^\r\n]+",
        r"\1\2***",
        text,
    )
    text = re.sub(
        r"(?i)(password|passToken|serviceToken|cookie|authorization|token)"
        r"([\"']?\s*[=:]\s*[\"']?)([^\s,;\"'}]+)",
        r"\1\2***",
        text,
    )
    return text.encode("utf-8")


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
            archive.writestr("miair.log", _redact_log_tail(log_tail, app.config))

    buffer.seek(0)
    return buffer
