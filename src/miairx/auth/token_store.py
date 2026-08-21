"""Secure token-store adapter for miservice-fork."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from miairx.config.secure_io import atomic_write_private_json

log = logging.getLogger(__name__)


class SecureTokenStore:
    """Persist Xiaomi service tokens atomically with private Unix permissions."""

    def __init__(self, token_path: str):
        self.token_path = Path(token_path)

    def load_token(self):
        if not self.token_path.is_file():
            return None
        try:
            with self.token_path.open(encoding="utf-8") as file:
                return json.load(file)
        except Exception as exc:  # noqa: BLE001 - corrupt tokens can be re-created
            log.warning("Could not load Xiaomi token store %s: %s", self.token_path, exc)
            return None

    def save_token(self, token=None) -> None:
        if token:
            try:
                atomic_write_private_json(self.token_path, token)
            except Exception as exc:  # noqa: BLE001 - match miservice store semantics
                log.error("Could not save Xiaomi token store %s: %s", self.token_path, exc)
        else:
            try:
                self.token_path.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("Could not remove Xiaomi token store %s: %s", self.token_path, exc)
