"""AirPlay mDNS service advertisement for MiAirX"""

import logging
import socket
import threading
import time
from typing import Optional

from zeroconf import ServiceInfo, Zeroconf, IPVersion
from zeroconf._exceptions import ServiceNameAlreadyRegistered, NonUniqueNameException

log = logging.getLogger(__name__)


class AirplayMdns:
    """AirPlay mDNS service advertiser using zeroconf."""

    def __init__(
        self,
        hostname: str,
        device_name: str,
        device_id: str,
        rtsp_port: int,
        shared_zeroconf: Optional[Zeroconf] = None,
    ):
        self.hostname = hostname
        self.device_name = device_name
        self.device_id = device_id
        self.rtsp_port = rtsp_port
        self.shared_zeroconf = shared_zeroconf
        self.zeroconf: Optional[Zeroconf] = None
        self.raop_info: Optional[ServiceInfo] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """Start mDNS advertisement in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run_mdns, daemon=True)
        self._thread.start()

    def _run_mdns(self):
        """Run mDNS in a separate thread."""
        try:
            # Get local IP address
            ip = self.hostname if self.hostname and self.hostname not in ("0.0.0.0", "127.0.0.1") else self._get_ip()
            ip_bytes = socket.inet_aton(ip)

            log.info(f"Starting AirPlay mDNS, IP: {ip}:{self.rtsp_port}")

            # Use shared zeroconf or create new one
            if self.shared_zeroconf:
                self.zeroconf = self.shared_zeroconf
                log.info("Using shared Zeroconf instance")
            else:
                self.zeroconf = Zeroconf(ip_version=IPVersion.All)
                log.info("Created new Zeroconf instance")

            # Build device ID (MAC address format without colons)
            device_id_clean = self.device_id.replace(":", "")

            # AirPlay features for audio only (AirPort Express compatible)
            features = (1 << 9) | (1 << 14) | (1 << 18) | (1 << 19) | (1 << 20) | (1 << 22) | (1 << 23) | (1 << 27)
            features_lo = features & 0xFFFFFFFF
            features_hi = (features >> 32) & 0xFFFFFFFF
            if features_hi > 0:
                features_str = f"0x{features_lo:X},0x{features_hi:X}"
            else:
                features_str = f"0x{features_lo:X}"

            # RAOP service properties
            raop_properties = {
                b"ch": b"2",              # Stereo
                b"cn": b"0,1,2,3",        # PCM, ALAC, AAC, AAC-ELD
                b"et": b"0,1",            # Encryption: none, RSA
                b"sv": b"false",
                b"da": b"true",
                b"sr": b"44100",          # Sample rate
                b"ss": b"16",             # Sample size
                b"vn": b"65537",
                b"tp": b"UDP",            # Transport protocol
                b"vs": b"105.1",          # Version
                b"am": b"AirPort4,107",   # Model
                b"sf": b"0x4",
                b"ft": features_str.encode(),
                b"md": b"0,1,2",          # Metadata
                b"pw": b"false",          # Password protected
                b"fn": self.device_name.encode(),
            }

            # Create RAOP service info
            self.raop_info = ServiceInfo(
                type_="_raop._tcp.local.",
                name=f"{device_id_clean}@{self.device_name}._raop._tcp.local.",
                addresses=[ip_bytes],
                port=self.rtsp_port,
                properties=raop_properties,
                server=f"{self.hostname}.local.",
            )

            # Register RAOP service (with retry on name conflict)
            registered = False
            for attempt in range(3):
                try:
                    self.zeroconf.register_service(self.raop_info, allow_name_change=True)
                    log.info(f"RAOP service registered: {device_id_clean}@{self.device_name}._raop._tcp.local.")
                    registered = True
                    break
                except (ServiceNameAlreadyRegistered, NonUniqueNameException) as e:
                    if attempt < 2:
                        log.warning(f"RAOP service name conflict ({type(e).__name__}), retrying ({attempt+1}/3)...")
                        try:
                            self.zeroconf.unregister_all_services()
                        except Exception:
                            pass
                        time.sleep(2)
                    else:
                        raise

            if not registered:
                log.error(f"Failed to register RAOP service")
                return

            log.info(f"AirPlay mDNS started")
            log.info(f"  Device name: {self.device_name}")
            log.info(f"  Device ID: {self.device_id}")
            log.info(f"  RTSP port: {self.rtsp_port}")

            # Keep thread running
            while self._running:
                time.sleep(1)

        except Exception as e:
            log.error(f"Failed to start AirPlay mDNS: {e}")
            import traceback
            log.error(traceback.format_exc())

    def stop(self):
        """Stop mDNS advertisement."""
        self._running = False

        if self.zeroconf and self.raop_info:
            try:
                if not self.zeroconf.loop.is_closed():
                    self.zeroconf.unregister_service(self.raop_info)
                    log.info(f"RAOP service unregistered: {self.device_name}")
            except Exception as e:
                log.error(f"Failed to unregister mDNS service: {e}")

        # Only close zeroconf if we created it (not shared)
        if self.zeroconf and not self.shared_zeroconf:
            try:
                self.zeroconf.close()
            except Exception:
                pass

        if self._thread:
            self._thread.join(timeout=2)

    def update_port(self, port: int):
        """Update RTSP port (called after dynamic port allocation)."""
        self.rtsp_port = port

    @staticmethod
    def _get_ip() -> str:
        """Get local IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
