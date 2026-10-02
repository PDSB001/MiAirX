import json
from types import SimpleNamespace

from miairx.config.models import AppConfig, SpeakerConfig
from miairx.core.health import build_health_snapshot
from miairx.protocols.airplay.server import AirplayServer


def test_airplay_runtime_excludes_session_secrets():
    server = AirplayServer("127.0.0.1", "Test", rtsp_port=7000, audio_port=7001)
    server._running = True
    server._session_active = True
    server._receiver = SimpleNamespace(
        received=20, decoded=18, lost=1, invalid=1, key=b"secret-key", peer="private-peer"
    )
    server._ap2_session = SimpleNamespace(
        events=SimpleNamespace(port=7100), shared=b"secret-shared"
    )
    status = server.runtime_status()
    server._receiver.clock = SimpleNamespace(fresh=True, samples=2, rtt=0.012)
    assert server.runtime_status()["timing"] == {
        "measured": True,
        "samples": 2,
        "rtt_ms": 12.0,
    }
    assert status["state"] == "playing"
    assert status["protocol"] == "ap2_realtime"
    assert status["event_port"] == 7100
    assert status["packets"] == {"received": 20, "decoded": 18, "lost": 1, "invalid": 1}
    assert "secret" not in json.dumps(status)
    assert "private-peer" not in json.dumps(status)
    server._receiver = server._ap2_session = None
    server._session_active = False
    assert server.runtime_status()["protocol"] is None
    assert server.runtime_status()["state"] == "idle"
    assert server.runtime_status()["event_port"] is None
    assert all(count == 0 for count in server.runtime_status()["packets"].values())


def test_classic_runtime_has_no_ap2_event_port():
    server = AirplayServer("127.0.0.1", "Test")
    server._receiver = SimpleNamespace(received=1, decoded=1, lost=0, invalid=0)
    assert server.runtime_status()["protocol"] == "raop"
    assert server.runtime_status()["state"] == "connected"
    assert server.runtime_status()["event_port"] is None


def test_health_includes_runtime_and_truthful_capabilities():
    config = AppConfig(mi_did="123", speakers={"123": SpeakerConfig(did="123", name="Test")})
    server = AirplayServer("127.0.0.1", "Test", rtsp_port=7000, audio_port=7001)
    app = SimpleNamespace(
        config=config, _airplay_services={"123": SimpleNamespace(airplay_server=server)}
    )
    health = build_health_snapshot(app)
    assert health["speakers"][0]["airplay"]["rtsp_port"] == 7000
    assert health["airplay"]["capabilities"]["ap2_realtime"] == "experimental"
    assert health["airplay"]["capabilities"]["ios_verified"] is False
    assert health["airplay"]["capabilities"]["ap2_discovery"] is False
