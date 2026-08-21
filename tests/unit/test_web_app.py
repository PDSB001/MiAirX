import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.web_fileresponse import FileResponse

from miairx.config.models import AppConfig
from miairx.web.app import (
    STATIC_DIR,
    create_web_app,
    handle_get_config,
    handle_health,
    handle_index,
    handle_legacy_index,
    handle_play,
    handle_save_config,
    handle_seek,
    handle_status,
    handle_volume,
)
from miairx.web.auth import _COOKIE_NAME


@pytest.mark.asyncio
async def test_react_console_is_default_index() -> None:
    response = await handle_index(None)  # type: ignore[arg-type]

    assert isinstance(response, FileResponse)
    assert Path(response._path) == STATIC_DIR / "app" / "index.html"


@pytest.mark.asyncio
async def test_legacy_console_remains_available() -> None:
    response = await handle_legacy_index(None)  # type: ignore[arg-type]

    assert isinstance(response, FileResponse)
    assert Path(response._path) == STATIC_DIR / "index.html"


@pytest.mark.asyncio
async def test_config_api_exposes_airplay_port_start() -> None:
    request = SimpleNamespace(app={"config": AppConfig(airplay_port_start=17000)})

    response = await handle_get_config(request)

    assert json.loads(response.text)["airplay_port_start"] == 17000


@pytest.mark.asyncio
async def test_health_endpoint_returns_runtime_snapshot(monkeypatch) -> None:
    expected = {"status": "ok", "xiaomi": {"status": "normal"}}
    monkeypatch.setattr("miairx.web.app.build_health_snapshot", lambda app: expected)
    request = SimpleNamespace(app={"app": object()})

    response = await handle_health(request)

    assert json.loads(response.text) == expected


def test_web_app_exposes_exact_health_route() -> None:
    app = create_web_app(AppConfig(), SimpleNamespace())
    paths = {route.resource.canonical for route in app.router.routes()}

    assert "/health" in paths


@pytest.mark.asyncio
async def test_status_uses_effective_hostname_when_config_is_blank() -> None:
    config = AppConfig(hostname="")
    app = SimpleNamespace(
        resolve_hostname=lambda: "192.168.1.23",
        _is_running=True,
    )
    request = SimpleNamespace(app={"config": config, "app": app})

    response = await handle_status(request)

    assert config.hostname == ""
    assert json.loads(response.text)["hostname"] == "192.168.1.23"


@pytest.mark.asyncio
async def test_play_reports_expired_xiaomi_login() -> None:
    controller = SimpleNamespace(play_url=AsyncMock())
    app = SimpleNamespace(
        auth=SimpleNamespace(login_status=lambda: "expired"),
        speaker_manager=SimpleNamespace(get_controller_by_did=lambda did: controller),
        _speaker_health={},
    )
    request = SimpleNamespace(
        app={"app": app},
        json=AsyncMock(return_value={"did": "123", "url": "https://example.com/a.mp3"}),
    )

    response = await handle_play(request)
    body = json.loads(response.text)

    assert response.status == 401
    assert body["error_code"] == "XIAOMI_AUTH_EXPIRED"
    controller.play_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_play_reports_offline_speaker() -> None:
    controller = SimpleNamespace(play_url=AsyncMock())
    app = SimpleNamespace(
        auth=SimpleNamespace(login_status=lambda: "normal"),
        speaker_manager=SimpleNamespace(get_controller_by_did=lambda did: controller),
        _speaker_health={"123": {"status": "offline"}},
    )
    request = SimpleNamespace(
        app={"app": app},
        json=AsyncMock(return_value={"did": "123", "url": "https://example.com/a.mp3"}),
    )

    response = await handle_play(request)

    assert response.status == 503
    assert json.loads(response.text)["error_code"] == "SPEAKER_UNAVAILABLE"
    controller.play_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_config_api_rejects_overlapping_airplay_range() -> None:
    config = AppConfig(dlna_port=8200, web_port=8300, airplay_port_start=7000)
    store = SimpleNamespace(save=AsyncMock())
    request = SimpleNamespace(
        app={"config": config, "config_store": store},
        json=AsyncMock(return_value={"airplay_port_start": 8199}),
    )

    response = await handle_save_config(request)

    assert response.status == 400
    assert config.airplay_port_start == 7000
    store.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_new_password_expires_current_session() -> None:
    """Changing the management password invalidates the current browser too."""
    config = AppConfig(web_password="")
    store = SimpleNamespace(save=AsyncMock())
    request = SimpleNamespace(
        app={"config": config, "config_store": store},
        json=AsyncMock(return_value={"web_password": "newpass123"}),
    )

    response = await handle_save_config(request)

    assert response.status == 200
    assert config.web_password == "newpass123"
    cookie = response.cookies.get(_COOKIE_NAME)
    assert cookie is not None
    assert cookie.value == ""
    assert cookie["max-age"] == "0"
    assert json.loads(response.text)["reauth_required"] is True


@pytest.mark.asyncio
async def test_save_placeholder_password_does_not_change() -> None:
    """The masked placeholder '***' means unchanged and must not re-issue."""
    config = AppConfig(web_password="existing")
    store = SimpleNamespace(save=AsyncMock())
    request = SimpleNamespace(
        app={"config": config, "config_store": store},
        json=AsyncMock(return_value={"web_password": "***"}),
    )

    response = await handle_save_config(request)

    assert response.status == 200
    assert config.web_password == "existing"
    assert _COOKIE_NAME not in response.cookies


@pytest.mark.asyncio
async def test_save_empty_password_disables_protection() -> None:
    """Disabling protection clears the cookie without requiring another login."""
    config = AppConfig(web_password="existing")
    store = SimpleNamespace(save=AsyncMock())
    request = SimpleNamespace(
        app={"config": config, "config_store": store},
        json=AsyncMock(return_value={"web_password": ""}),
    )

    response = await handle_save_config(request)

    assert response.status == 200
    assert config.web_password == ""
    cookie = response.cookies.get(_COOKIE_NAME)
    assert cookie is not None
    assert cookie.value == ""
    assert cookie["max-age"] == "0"
    assert json.loads(response.text)["reauth_required"] is False


@pytest.mark.asyncio
async def test_invalid_config_update_is_transactional() -> None:
    config = AppConfig(account="old", default_volume=30)
    store = SimpleNamespace(save=AsyncMock())
    request = SimpleNamespace(
        app={"config": config, "config_store": store},
        json=AsyncMock(return_value={"account": "new", "default_volume": 101}),
    )

    response = await handle_save_config(request)

    assert response.status == 400
    assert config.account == "old"
    assert config.default_volume == 30
    store.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_config_boolean_coercion_is_owned_by_pydantic() -> None:
    config = AppConfig(verbose=True)
    store = SimpleNamespace(save=AsyncMock())
    request = SimpleNamespace(
        app={"config": config, "config_store": store},
        json=AsyncMock(return_value={"verbose": "false"}),
    )

    response = await handle_save_config(request)

    assert response.status == 200
    assert config.verbose is False


@pytest.mark.asyncio
@pytest.mark.parametrize("volume", [-1, 0, 101, "loud"])
async def test_volume_api_rejects_out_of_range_values(volume) -> None:
    request = SimpleNamespace(json=AsyncMock(return_value={"did": "123", "volume": volume}))

    response = await handle_volume(request)

    assert response.status == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("position", [-1, float("inf"), 86401])
async def test_seek_api_rejects_out_of_range_values(position) -> None:
    request = SimpleNamespace(json=AsyncMock(return_value={"did": "123", "position": position}))

    response = await handle_seek(request)

    assert response.status == 400


@pytest.mark.asyncio
async def test_seek_api_rejects_position_after_track_end() -> None:
    renderer = SimpleNamespace(_track_duration=60.0, seek=AsyncMock())
    app = SimpleNamespace(_did_to_udn={"123": "uuid:test"}, renderers={"uuid:test": renderer})
    request = SimpleNamespace(
        app={"app": app},
        json=AsyncMock(return_value={"did": "123", "position": 61}),
    )

    response = await handle_seek(request)

    assert response.status == 400
    renderer.seek.assert_not_awaited()
