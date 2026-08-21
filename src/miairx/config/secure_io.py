"""Private, atomic JSON storage for files containing credentials."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _chmod_if_posix(path: Path, mode: int) -> None:
    """Apply restrictive Unix permissions without breaking non-POSIX hosts."""
    if os.name != "posix":
        return
    try:
        os.chmod(path, mode)
    except OSError as exc:
        log.warning("Could not restrict permissions on %s: %s", path, exc)


def ensure_private_directory(path: Path) -> None:
    """Create a credential directory and restrict it to its owner on Unix."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    _chmod_if_posix(path, 0o700)


def atomic_write_private_json(path: Path, data: Any) -> None:
    """Atomically write JSON, attempting mode 0600 for the resulting file."""
    ensure_private_directory(path.parent)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        _chmod_if_posix(tmp_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
        _chmod_if_posix(path, 0o600)
    except Exception:
        with suppress(OSError):
            os.close(fd)
        with suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise
