"""Atomic configuration store for MiAirX"""

import json
import logging
import os
from pathlib import Path

from miairx.config.models import AppConfig

log = logging.getLogger(__name__)


class ConfigStore:
    """Atomic JSON configuration store."""

    def __init__(self, conf_path: str = "conf"):
        self.conf_path = Path(conf_path)
        self.config_file = self.conf_path / "config.json"

    def load(self) -> AppConfig:
        """Load configuration from file."""
        if not self.config_file.exists():
            log.info(f"Config file not found at {self.config_file}")
            log.info("Creating default configuration...")
            
            # Create default config
            config = AppConfig(conf_path=str(self.conf_path))
            
            # Save default config to file
            try:
                self.save_sync(config)
                log.info(f"Default configuration saved to {self.config_file}")
                log.info("Please edit the configuration file or use Web UI to configure.")
            except Exception as e:
                log.warning(f"Failed to save default config: {e}")
            
            return config

        try:
            with open(self.config_file, encoding="utf-8") as f:
                data = json.load(f)
            
            # Set conf_path from the store
            data["conf_path"] = str(self.conf_path)
            
            # Filter valid fields
            valid_fields = set(AppConfig.model_fields.keys())
            filtered_data = {k: v for k, v in data.items() if k in valid_fields}
            
            return AppConfig(**filtered_data)
        except Exception as e:
            log.error(f"Failed to load config: {e}")
            return AppConfig(conf_path=str(self.conf_path))

    async def save(self, config: AppConfig) -> None:
        """Save configuration to file atomically."""
        try:
            # Ensure directory exists
            self.conf_path.mkdir(parents=True, exist_ok=True)
            
            # Prepare data for serialization
            data = config.model_dump()
            
            # Write to temporary file first
            tmp_path = self.config_file.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # Atomic rename (os.replace is atomic on most systems)
            os.replace(tmp_path, self.config_file)
            
            log.info(f"Configuration saved to {self.config_file}")
        except Exception as e:
            log.error(f"Failed to save config: {e}")
            raise

    def load_sync(self) -> AppConfig:
        """Synchronous version of load for backwards compatibility."""
        return self.load()

    def save_sync(self, config: AppConfig) -> None:
        """Synchronous version of save."""
        try:
            # Ensure directory exists
            self.conf_path.mkdir(parents=True, exist_ok=True)
            
            # Prepare data for serialization
            data = config.model_dump()
            
            # Write to temporary file first
            tmp_path = self.config_file.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # Atomic rename
            os.replace(tmp_path, self.config_file)
            
            log.info(f"Configuration saved to {self.config_file}")
        except Exception as e:
            log.error(f"Failed to save config: {e}")
            raise
