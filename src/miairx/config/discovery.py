"""Configuration discovery utilities for MiAirX"""

import ipaddress
import logging
import os
import socket

log = logging.getLogger(__name__)


def detect_local_ip() -> str:
    """Auto-detect a usable IPv4 address without sending network traffic."""

    def is_usable(candidate: str) -> bool:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            return False
        return (
            address.version == 4
            and not address.is_loopback
            and not address.is_unspecified
            and not address.is_link_local
            and not address.is_multicast
        )

    # UDP connect only asks the kernel which source address its default route
    # would use; no packet needs to be exchanged with these destinations.
    for destination in ("223.5.5.5", "1.1.1.1", "8.8.8.8"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((destination, 80))
            candidate = sock.getsockname()[0]
            if is_usable(candidate):
                return candidate
        except OSError:
            pass
        finally:
            sock.close()

    # Devices without a default route may still have a valid LAN interface.
    try:
        candidates = {
            item[4][0]
            for item in socket.getaddrinfo(
                socket.gethostname(),
                None,
                family=socket.AF_INET,
                type=socket.SOCK_DGRAM,
            )
        }
        usable = [candidate for candidate in candidates if is_usable(candidate)]
        if usable:
            # Prefer RFC1918 addresses, then keep the result deterministic.
            return sorted(
                usable,
                key=lambda candidate: (
                    not ipaddress.ip_address(candidate).is_private,
                    candidate,
                ),
            )[0]
    except OSError:
        pass

    log.warning("Unable to detect a LAN IPv4 address; falling back to loopback")
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
