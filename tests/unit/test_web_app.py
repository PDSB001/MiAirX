import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.web_fileresponse import FileResponse

from miairx.config.models import AppConfig
from miairx.web.app import (
    STATIC_DIR,
    handle_get_config,
    handle_index,
    handle_legacy_index,
    handle_save_config,
)
from miairx.web.auth import _COOKIE_NAME, verify_token


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
async def test_save_new_password_reissues_token() -> None:
    """Setting a web password must re-issue a token signed with the new password."""
    config = AppConfig(web_password="")
    store = SimpleNamespace(save=AsyncMock())
    request = SimpleNamespace(
        app={"config": config, "config_store": store},
        json=AsyncMock(return_value={"web_password": "newpass123"}),
    )

    response = await handle_save_config(request)

    assert response.status == 200
    assert config.web_password == "newpass123"
    # The Set-Cookie must contain a token valid under the NEW password, so the
    # client's post-save refresh requests succeed instead of 401.
    cookie = response.cookies.get(_COOKIE_NAME)
    assert cookie is not None
    assert verify_token("newpass123", cookie.value)
    # The old (empty) password must no longer validate the new token.
    assert not verify_token("", cookie.value)


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
    """An explicit empty web_password clears the password and re-issues a token."""
    config = AppConfig(web_password="existing")
    store = SimpleNamespace(save=AsyncMock())
    request = SimpleNamespace(
        app={"config": config, "config_store": store},
        json=AsyncMock(return_value={"web_password": ""}),
    )

    response = await handle_save_config(request)

    assert response.status == 200
    assert config.web_password == ""
    # The token cookie is still re-issued for consistency, but an empty
    # password disables protection entirely (verify_token always returns False
    # for an empty password, and the middleware skips auth when disabled).
    cookie = response.cookies.get(_COOKIE_NAME)
    assert cookie is not None
    assert not verify_token("", cookie.value)
