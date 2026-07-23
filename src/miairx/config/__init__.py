"""Configuration module for MiAirX"""

from miairx.config.discovery import detect_local_ip, find_free_port, get_hostname, merge_env_vars
from miairx.config.models import AppConfig, SpeakerConfig
from miairx.config.store import ConfigStore

__all__ = [
    "AppConfig",
    "SpeakerConfig",
    "ConfigStore",
    "detect_local_ip",
    "find_free_port",
    "get_hostname",
    "merge_env_vars",
]
