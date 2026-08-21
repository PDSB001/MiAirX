from types import SimpleNamespace

from miairx.config.models import AppConfig, SpeakerConfig
from miairx.core.health import build_health_snapshot


def test_health_snapshot_keeps_offline_speaker_configuration() -> None:
    config = AppConfig(
        mi_did="123",
        speakers={
            "123": SpeakerConfig(
                did="123",
                name="Living Room",
                hardware="L05C",
            ),
        },
    )
    app = SimpleNamespace(
        config=config,
        _is_running=True,
        auth=SimpleNamespace(login_status=lambda: "normal"),
        dlna_server=SimpleNamespace(_site=object()),
        ssdp=SimpleNamespace(_transport=object()),
        _zeroconf=object(),
        _airplay_services={"123": SimpleNamespace(_airplay_active=False, airplay_server=SimpleNamespace(_running=True))},
        _speaker_health={"123": {"status": "offline"}},
        resolve_hostname=lambda: "192.168.1.5",
    )

    snapshot = build_health_snapshot(app)

    assert snapshot["speakers"] == [{
        "did": "123",
        "name": "Living Room",
        "model": "L05C",
        "status": "offline",
        "current_source": None,
    }]
    assert config.mi_did == "123"
    assert snapshot["status"] == "degraded"
