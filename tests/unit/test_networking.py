"""Network-stack regression tests."""

import socket
from unittest.mock import AsyncMock, MagicMock

import pytest
from zeroconf import IPVersion

import miairx.app as app_module
import miairx.protocols.dlna.ssdp as ssdp_module
from miairx.app import Application
from miairx.config.models import AppConfig
from miairx.const import SSDP_PORT
from miairx.protocols.dlna.ssdp import SsdpServer


@pytest.mark.asyncio
async def test_airplay_zeroconf_is_ipv4_only(monkeypatch):
    """Containers without IPv6 must not attempt mDNS traffic via ::1."""
    zeroconf = MagicMock()
    monkeypatch.setattr(app_module, "Zeroconf", zeroconf)
    application = Application(AppConfig(hostname="127.0.0.1"))

    await application._start_airplay_server()

    zeroconf.assert_called_once_with(ip_version=IPVersion.V4Only)


@pytest.mark.asyncio
async def test_airplay_services_receive_fixed_port_pairs(monkeypatch):
    """Docker firewall rules rely on deterministic per-speaker TCP ports."""
    calls = []

    class FakeSpeakerAirplay:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def start(self):
            return None

    monkeypatch.setattr(app_module, "Zeroconf", MagicMock())
    monkeypatch.setattr(app_module, "SpeakerAirplay", FakeSpeakerAirplay)

    application = Application(
        AppConfig(
            hostname="192.168.1.20",
            mi_did="speaker-a,speaker-b",
            airplay_port_start=7000,
        )
    )
    application.speaker_manager = MagicMock()
    application.speaker_manager.get_controller_by_did.return_value = MagicMock()

    await application._start_airplay_server()

    assert [(call["rtsp_port"], call["audio_port"]) for call in calls] == [
        (7000, 7001),
        (7002, 7003),
    ]


@pytest.mark.asyncio
async def test_partial_startup_is_cleaned_up():
    """A startup failure must close the HTTP session even before running."""
    application = Application(AppConfig(hostname="127.0.0.1"))
    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    application.session = session

    await application.stop()

    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_docker_ssdp_binds_wildcard_and_selects_multicast_interface(
    monkeypatch,
):
    """Docker must receive on every address while sending via the LAN NIC."""
    fake_socket = MagicMock()
    fake_transport = MagicMock()
    loop = MagicMock()
    loop.create_datagram_endpoint = AsyncMock(
        return_value=(fake_transport, MagicMock())
    )

    monkeypatch.setattr(ssdp_module.socket, "socket", MagicMock(return_value=fake_socket))
    monkeypatch.setattr(ssdp_module.asyncio, "get_running_loop", lambda: loop)
    monkeypatch.setattr(SsdpServer, "_is_docker", staticmethod(lambda: True))

    server = SsdpServer("192.168.1.20", 8200)
    await server.start()
    try:
        fake_socket.bind.assert_called_once_with(("", SSDP_PORT))
        assert (
            socket.IPPROTO_IP,
            socket.IP_MULTICAST_IF,
            socket.inet_aton("192.168.1.20"),
        ) in [entry.args for entry in fake_socket.setsockopt.call_args_list]
    finally:
        await server.stop()


def test_docker_msearch_replies_finish_within_quarter_second(monkeypatch):
    """All ssdp:all responses should be scheduled promptly in Docker."""
    loop = MagicMock()
    transport = MagicMock()
    monkeypatch.setattr(ssdp_module.asyncio, "get_running_loop", lambda: loop)
    monkeypatch.setattr(SsdpServer, "_is_docker", staticmethod(lambda: True))

    server = SsdpServer("192.168.1.20", 8200)
    server.register_renderer("uuid:test", "Test renderer")
    server._transport = transport
    request = (
        b"M-SEARCH * HTTP/1.1\r\n"
        b"HOST: 239.255.255.250:1900\r\n"
        b'MAN: "ssdp:discover"\r\n'
        b"MX: 3\r\n"
        b"ST: ssdp:all\r\n\r\n"
    )

    server.handle_msearch(request, ("192.168.1.50", 12345))

    assert loop.call_later.call_count == 6
    delays = [entry.args[0] for entry in loop.call_later.call_args_list]
    assert min(delays) >= 0
    assert max(delays) <= 0.25


@pytest.mark.asyncio
async def test_ssdp_repeats_alive_announcements_during_startup(monkeypatch):
    """Startup sends three retry bursts to tolerate multicast packet loss."""
    sleep = AsyncMock()
    monkeypatch.setattr(ssdp_module.asyncio, "sleep", sleep)
    server = SsdpServer("192.168.1.20", 8200)
    server._send_alive = AsyncMock()

    await server._send_startup_alive_burst()

    assert sleep.await_args_list == [
        ((0.15,), {}),
        ((0.35,), {}),
        ((0.75,), {}),
    ]
    assert server._send_alive.await_count == 3
