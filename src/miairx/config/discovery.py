"""Configuration discovery utilities for MiAirX"""

import logging
import os
import socket

log = logging.getLogger(__name__)


def detect_local_ip() -> str:
    """Auto-detect local LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_hostname() -> str:
    """Get system hostname."""
    try:
        return socket.gethostname()
    except Exception:
        return "localhost"


def merge_env_vars(config_data: dict) -> dict:
    """Merge environment variables into configuration data."""
    env_mapping = {
        "MI_USER": "account",
        "MI_PASS": "password",
        "MI_DID": "mi_did",
        "MIAIR_HOSTNAME": "hostname",
        "MIAIR_DLNA_PORT": "dlna_port",
        "MIAIR_WEB_PORT": "web_port",
        "MIAIR_VERBOSE": "verbose",
    }
    
    for env_var, config_key in env_mapping.items():
        value = os.getenv(env_var)
        if value is not None:
            # Type conversion for numeric values
            if config_key in ("dlna_port", "web_port"):
                try:
                    value = int(value)
                except ValueError:
                    log.warning(f"Invalid {env_var} value: {value}, ignoring")
                    continue
            elif config_key == "verbose":
                value = value.lower() in ("true", "1", "yes")
            
            # Only set if not already configured
            if config_key not in config_data or not config_data[config_key]:
                config_data[config_key] = value
    
    return config_data


def find_free_port(start_port: int = 8200) -> int:
    """Find a free port starting from the given port."""
    for port in range(start_port, start_port + 100):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", port))
                return port
        except OSError:
            continue
    return start_port
