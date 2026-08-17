"""Unit tests for hot-reload coverage after a config save."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from miairx.app import Application
from miairx.config.models import AppConfig


def _make_app(**overrides):
    app = MagicMock()
    app.auth = MagicMock()
    app.speaker_manager = MagicMock()
    app.speaker_manager.rebuild = AsyncMock()
    app.config = AppConfig(conf_path="/tmp/test")
    app.restart_dlna = AsyncMock()
    app.restart_airplay = AsyncMock()
    for key, value in overrides.items():
        setattr(app, key, value)
    return app


@pytest.mark.asyncio
async def test_volume_change_restarts_renderers():
    """default_volume / follow_device_volume rebuild DLNA + AirPlay."""
    app = _make_app()

    result = await Application.reload_after_config_change(app, {"default_volume"})

    assert result is False
    app.restart_dlna.assert_awaited_once()
    app.restart_airplay.assert_awaited_once()
    app.speaker_manager.rebuild.assert_not_awaited()


@pytest.mark.asyncio
async def test_credential_change_invalidates_and_rebuilds():
    app = _make_app()

    result = await Application.reload_after_config_change(app, {"cookie"})

    assert result is False
    app.auth.invalidate_session.assert_called_once()
    app.speaker_manager.rebuild.assert_awaited_once()
    app.restart_dlna.assert_awaited_once()
    app.restart_airplay.assert_awaited_once()


@pytest.mark.asyncio
async def test_verbose_change_reconfigures_logging():
    app = _make_app()

    with patch("miairx.core.logging.setup_logging") as setup_logging:
        result = await Application.reload_after_config_change(app, {"verbose"})

    assert result is False
    setup_logging.assert_called_once_with(
        verbose=app.config.verbose, log_file=app.config.log_file
    )
    # Verbose-only change must not restart services.
    app.restart_dlna.assert_not_awaited()
    app.restart_airplay.assert_not_awaited()


@pytest.mark.asyncio
async def test_web_port_requires_full_restart():
    app = _make_app()

    result = await Application.reload_after_config_change(app, {"web_port"})

    assert result is True
    app.restart_dlna.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_field_does_not_restart():
    """auto_resume_on_interrupt etc. take effect via the shared config."""
    app = _make_app()

    result = await Application.reload_after_config_change(app, {"auto_resume_on_interrupt"})

    assert result is False
    app.restart_dlna.assert_not_awaited()
    app.restart_airplay.assert_not_awaited()
    app.speaker_manager.rebuild.assert_not_awaited()
