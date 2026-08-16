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
