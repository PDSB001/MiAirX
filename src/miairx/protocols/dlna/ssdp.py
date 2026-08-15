"""SSDP (Simple Service Discovery Protocol) server for MiAirX"""

import asyncio
import logging
import os
import random
import socket
import struct
from typing import Optional

from miairx.const import (
    AVTRANSPORT_URN,
    CONNECTION_MANAGER_URN,
    DEVICE_TYPE,
    RENDERING_CONTROL_URN,
    SSDP_ADDR,
    SSDP_ALIVE_INTERVAL,
    SSDP_PORT,
)

log = logging.getLogger(__name__)


class SsdpProtocol(asyncio.DatagramProtocol):
    """SSDP UDP protocol handler."""

    def __init__(self, server: "SsdpServer"):
        self.server = server

    def datagram_received(self, data: bytes, addr: tuple):
        self.server.handle_msearch(data, addr)

    def error_received(self, exc):
        log.warning(f"SSDP error: {exc}")


class SsdpServer:
    """SSDP multicast server for device discovery."""

    _STARTUP_ALIVE_DELAYS = (0.15, 0.35, 0.75)
    _MAX_MSEARCH_DELAY = 0.5
    _DOCKER_MAX_MSEARCH_DELAY = 0.25
    _MSEARCH_RESPONSE_SPACING = 0.01

    def __init__(self, hostname: str, dlna_port: int):
        self.hostname = hostname
        self.dlna_port = dlna_port
        self.renderers: dict[str, str] = {}  # udn -> friendly_name
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._alive_task: Optional[asyncio.Task] = None
        self._startup_alive_task: Optional[asyncio.Task] = None
        self._sock: Optional[socket.socket] = None

        # Pre-built message caches (built once at registration, reused forever)
        self._alive_msgs: dict[str, list[bytes]] = {}  # udn -> [msg_bytes, ...]
        self._msearch_replies: dict[str, dict[str, bytes]] = {}  # udn -> {st: msg_bytes}

    def _pre_build_messages(self, udn: str) -> None:
        """Pre-build all SSDP messages for a renderer (called once at registration)."""
        targets = self._get_search_targets(udn)

        # Pre-build NOTIFY alive messages
        alive = [self._build_notify_alive(nt, usn, udn) for nt, usn in targets]
        self._alive_msgs[udn] = alive

        # Pre-build M-SEARCH response messages
        replies = {}
        for nt, usn in targets:
            replies[nt] = self._build_msearch_response(nt, usn, udn)
        self._msearch_replies[udn] = replies

    def register_renderer(self, udn: str, friendly_name: str):
        """Register a renderer and pre-build SSDP messages."""
        self.renderers[udn] = friendly_name
        self._pre_build_messages(udn)
        log.info(f"SSDP registered renderer: {friendly_name} (uuid:{udn})")

    def _get_location(self, udn: str) -> str:
        """Get device description URL."""
        return f"http://{self.hostname}:{self.dlna_port}/device/{udn}/description.xml"

    def _get_search_targets(self, udn: str) -> list[tuple[str, str]]:
        """Get all ST/USN pairs to advertise.

        Note: udn may already contain 'uuid:' prefix (e.g. from SpeakerConfig
        or HTTP server routing). Strip it to avoid double-prefixing the USN.
        """
        bare = udn[6:] if udn.startswith("uuid:") else udn
        uuid_str = f"uuid:{bare}"
        return [
            ("upnp:rootdevice", f"{uuid_str}::upnp:rootdevice"),
            (uuid_str, uuid_str),
            (DEVICE_TYPE, f"{uuid_str}::{DEVICE_TYPE}"),
            (AVTRANSPORT_URN, f"{uuid_str}::{AVTRANSPORT_URN}"),
            (RENDERING_CONTROL_URN, f"{uuid_str}::{RENDERING_CONTROL_URN}"),
            (CONNECTION_MANAGER_URN, f"{uuid_str}::{CONNECTION_MANAGER_URN}"),
        ]

    def _build_msearch_response(self, st: str, usn: str, udn: str) -> bytes:
        """Build M-SEARCH response."""
        location = self._get_location(udn)
        response = (
            "HTTP/1.1 200 OK\r\n"
            f"CACHE-CONTROL: max-age=1800\r\n"
            f"LOCATION: {location}\r\n"
            f"SERVER: MiAirX/1.0 UPnP/1.0\r\n"
            f"ST: {st}\r\n"
            f"USN: {usn}\r\n"
            f"EXT:\r\n"
            "\r\n"
        )
        return response.encode("utf-8")

    def _build_notify_alive(self, nt: str, usn: str, udn: str) -> bytes:
        """Build NOTIFY alive message."""
        location = self._get_location(udn)
        notify = (
            "NOTIFY * HTTP/1.1\r\n"
            f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
            f"CACHE-CONTROL: max-age=1800\r\n"
            f"LOCATION: {location}\r\n"
            f"NT: {nt}\r\n"
            f"NTS: ssdp:alive\r\n"
            f"SERVER: MiAirX/1.0 UPnP/1.0\r\n"
            f"USN: {usn}\r\n"
            "\r\n"
        )
        return notify.encode("utf-8")

    def _build_notify_byebye(self, nt: str, usn: str) -> bytes:
        """Build NOTIFY byebye message."""
        notify = (
            "NOTIFY * HTTP/1.1\r\n"
            f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
            f"NT: {nt}\r\n"
            f"NTS: ssdp:byebye\r\n"
            f"USN: {usn}\r\n"
            "\r\n"
        )
        return notify.encode("utf-8")

    @staticmethod
    def _is_docker() -> bool:
        """Detect if running inside a Docker container."""
        return os.path.isfile("/.dockerenv")

    def _resolve_bind_ip(self) -> str:
        """Return the interface IP used for SSDP multicast traffic.

        The receive socket must still bind to INADDR_ANY so it receives
        multicast M-SEARCH packets. This address only selects the interface
        used to join the group and send multicast traffic from Docker.
        """
        if not SsdpServer._is_docker():
            return ""  # INADDR_ANY
        # Docker: prefer configured hostname, fall back to detection.
        if self.hostname and self.hostname not in ("", "0.0.0.0"):
            try:
                socket.inet_aton(self.hostname)
                return self.hostname
            except OSError:
                pass
        return SsdpServer._detect_lan_ip()

    @staticmethod
    def _detect_lan_ip() -> str:
        """Detect LAN IP by probing an external address."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except OSError:
            return ""

    async def start(self):
        """Start SSDP server."""
        loop = asyncio.get_running_loop()

        bind_ip = self._resolve_bind_ip()
        in_docker = SsdpServer._is_docker()

        # Create UDP socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # SO_REUSEPORT can load-balance UDP packets between listeners on
        # Linux. Avoid it in Docker, where that can make M-SEARCH packets
        # intermittently land in a different host process.
        if not in_docker and hasattr(socket, "SO_REUSEPORT"):
            try:
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass

        # Always receive on every local address. Binding to a specific LAN IP
        # can exclude multicast packets on Linux/host-networked containers.
        self._sock.bind(("", SSDP_PORT))

        # Docker: tell kernel which interface to use for multicast
        if in_docker and bind_ip:
            self._sock.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                socket.inet_aton(bind_ip),
            )

        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

        # Join multicast group
        iface = bind_ip if in_docker and bind_ip else "0.0.0.0"
        mreq = struct.pack(
            "4s4s",
            socket.inet_aton(SSDP_ADDR),
            socket.inet_aton(iface),
        )
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self._sock.setblocking(False)

        # Create asyncio datagram endpoint
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: SsdpProtocol(self),
            sock=self._sock,
        )

        # Send initial alive
        await self._send_alive()

        # UDP multicast is lossy, especially while a host-networked container
        # is still settling. Repeat the initial advertisements in a short
        # burst so clients discover renderers without waiting for the next
        # periodic announcement.
        self._startup_alive_task = asyncio.create_task(
            self._send_startup_alive_burst()
        )

        # Start periodic alive task
        self._alive_task = asyncio.create_task(self._periodic_alive())
        log.info(
            "SSDP server started "
            f"(group={SSDP_ADDR}:{SSDP_PORT}, interface={bind_ip or 'default'}, "
            f"docker={in_docker})"
        )

    async def stop(self):
        """Stop SSDP server."""
        if self._startup_alive_task:
            self._startup_alive_task.cancel()
            try:
                await self._startup_alive_task
            except asyncio.CancelledError:
                pass
            self._startup_alive_task = None

        # Send byebye (with timeout)
        try:
            await asyncio.wait_for(self._send_byebye(), timeout=2.0)
        except asyncio.TimeoutError:
            log.warning("SSDP byebye send timeout")
        except Exception:
            pass

        if self._alive_task:
            self._alive_task.cancel()
            try:
                await asyncio.wait_for(self._alive_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        if self._transport:
            self._transport.close()
            self._transport = None

        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        log.info("SSDP server stopped")

    async def _send_alive(self):
        """Send pre-built NOTIFY alive messages."""
        if not self._transport:
            return
        for udn in self.renderers:
            for data in self._alive_msgs.get(udn, ()):
                self._transport.sendto(data, (SSDP_ADDR, SSDP_PORT))

    async def _send_startup_alive_burst(self):
        """Repeat alive announcements shortly after startup."""
        try:
            for delay in self._STARTUP_ALIVE_DELAYS:
                await asyncio.sleep(delay)
                await self._send_alive()
        except asyncio.CancelledError:
            pass

    async def _send_byebye(self):
        """Send NOTIFY byebye."""
        if not self._transport:
            return
        for udn in self.renderers:
            for nt, usn in self._get_search_targets(udn):
                data = self._build_notify_byebye(nt, usn)
                self._transport.sendto(data, (SSDP_ADDR, SSDP_PORT))

    async def _periodic_alive(self):
        """Periodically send alive notifications."""
        try:
            while True:
                await asyncio.sleep(SSDP_ALIVE_INTERVAL + random.uniform(-5, 5))
                await self._send_alive()
        except asyncio.CancelledError:
            pass

    def handle_msearch(self, data: bytes, addr: tuple):
        """Handle M-SEARCH request (uses pre-built cached responses)."""
        try:
            message = data.decode("utf-8")
        except UnicodeDecodeError:
            return

        request_line = message.split("\r\n", 1)[0].upper()
        if not request_line.startswith("M-SEARCH "):
            return

        # Parse ST (Search Target) and MX
        st = ""
        mx = 3
        for line in message.split("\r\n"):
            lower = line.lower()
            if lower.startswith("st:"):
                st = line.split(":", 1)[1].strip()
            elif lower.startswith("mx:"):
                try:
                    mx = int(line.split(":", 1)[1].strip())
                except ValueError:
                    mx = 3

        if not st:
            return

        # Gather cached responses for each matching renderer.
        normalized_st = st.lower()
        responses = []
        for udn in self.renderers:
            replies = self._msearch_replies.get(udn, {})
            targets = self._get_search_targets(udn)
            for target_st, _target_usn in targets:
                if normalized_st == "ssdp:all" or normalized_st == target_st.lower():
                    response = replies.get(target_st)
                    if response is not None:
                        responses.append(response)

        transport = self._transport
        if not responses or transport is None:
            return

        # The previous implementation independently delayed every reply by as
        # much as three seconds. A small randomized window still avoids a LAN
        # response implosion while making Docker discovery feel immediate.
        max_delay = (
            self._DOCKER_MAX_MSEARCH_DELAY
            if self._is_docker()
            else self._MAX_MSEARCH_DELAY
        )
        response_window = max(0.0, min(float(mx), max_delay))
        spacing = min(
            self._MSEARCH_RESPONSE_SPACING,
            response_window / max(len(responses), 1),
        )
        latest_base = max(0.0, response_window - spacing * (len(responses) - 1))
        base_delay = random.uniform(0.0, latest_base) if latest_base else 0.0
        loop = asyncio.get_running_loop()

        for index, response in enumerate(responses):
            loop.call_later(
                base_delay + spacing * index,
                transport.sendto,
                response,
                addr,
            )
