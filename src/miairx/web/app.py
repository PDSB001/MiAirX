"""Web application factory for MiAirX"""

import asyncio
import ipaddress
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from aiohttp import web
from pydantic import BaseModel, Field, ValidationError

from miairx import __version__
from miairx.auth.qr_login import STATE_CONFIRMED
from miairx.config.models import AppConfig
from miairx.config.store import ConfigStore
from miairx.core.health import build_health_snapshot
from miairx.core.log_buffer import get_log_buffer
from miairx.core.playback_errors import (
    PLAYBACK_ERROR_MESSAGES,
    PlaybackErrorCode,
    classify_playback_exception,
)
from miairx.web.auth import (
    _COOKIE_NAME,
    _LOGIN_LIMITER_KEY,
    LoginRateLimiter,
    auth_middleware,
    handle_auth_login,
    handle_auth_logout,
    handle_auth_status,
)
from miairx.web.diagnostics import build_diagnostics_bundle

if TYPE_CHECKING:
    from miairx.app import Application

log = logging.getLogger(__name__)


class VolumeRequest(BaseModel):
    """Validated volume-control payload."""

    did: str = Field(min_length=1, max_length=128)
    volume: int = Field(ge=1, le=100)


class SeekRequest(BaseModel):
    """Validated seek-control payload."""

    did: str = Field(min_length=1, max_length=128)
    position: float = Field(ge=0, le=24 * 60 * 60, allow_inf_nan=False)


# Static files directory
STATIC_DIR = Path(__file__).parent / "static"


def create_web_app(config: "AppConfig", app: "Application", config_store: ConfigStore = None) -> web.Application:
    """Create web application for management interface.
    
    Args:
        config: Application configuration
        app: Main application instance
        config_store: Configuration store for saving settings
        
    Returns:
        Configured aiohttp web application
    """
    web_app = web.Application(middlewares=[auth_middleware])
    
    # Store references
    web_app["config"] = config
    web_app["app"] = app
    web_app["config_store"] = config_store or ConfigStore(config.conf_path)
    web_app[_LOGIN_LIMITER_KEY] = LoginRateLimiter()
    
    # Setup routes
    web_app.router.add_get("/", handle_index)
    web_app.router.add_get("/legacy", handle_legacy_index)
    web_app.router.add_get("/favicon.ico", handle_favicon)
    web_app.router.add_get("/api/auth/status", handle_auth_status)
    web_app.router.add_post("/api/auth/login", handle_auth_login)
    web_app.router.add_post("/api/auth/logout", handle_auth_logout)
    web_app.router.add_post("/api/auth/qrcode", handle_qr_start)
    web_app.router.add_get("/api/auth/qrcode/poll", handle_qr_poll)
    web_app.router.add_get("/api/status", handle_status)
    web_app.router.add_get("/health", handle_health)
    web_app.router.add_get("/api/health", handle_health)
    web_app.router.add_get("/api/version", handle_version)
    web_app.router.add_get("/api/logs/stream", handle_log_stream)
    web_app.router.add_get("/api/diagnostics", handle_diagnostics)
    web_app.router.add_get("/api/config", handle_get_config)
    web_app.router.add_post("/api/config", handle_save_config)
    web_app.router.add_get("/api/speakers", handle_speakers)
    web_app.router.add_get("/api/devices", handle_devices)
    web_app.router.add_get("/api/devices/discover", handle_discover_speakers)
    web_app.router.add_post("/api/play", handle_play)
    web_app.router.add_post("/api/pause", handle_pause)
    web_app.router.add_post("/api/stop", handle_stop)
    web_app.router.add_post("/api/volume", handle_volume)
    web_app.router.add_get("/api/positions", handle_get_positions)
    web_app.router.add_post("/api/seek", handle_seek)
    web_app.router.add_static("/static/", path=STATIC_DIR, name="static")
    
    return web_app


async def handle_index(request: web.Request) -> web.Response:
    """Serve the React management console."""
    app_index = STATIC_DIR / "app" / "index.html"
    if app_index.exists():
        return web.FileResponse(app_index)
    log.warning("React web assets are missing; falling back to the legacy console")
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_legacy_index(request: web.Request) -> web.Response:
    """Serve the previous single-file console as a recovery fallback."""
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_favicon(request: web.Request) -> web.Response:
    """Serve the MiAirX logo for legacy favicon requests."""
    return web.FileResponse(STATIC_DIR / "logo.png")


async def handle_status(request: web.Request) -> web.Response:
    """Handle status API endpoint."""
    config = request.app["config"]
    app = request.app["app"]
    
    status = {
        "version": __version__,
        "hostname": app.resolve_hostname(),
        "dlna_port": config.dlna_port,
        "web_port": config.web_port,
        "airplay_port_start": config.airplay_port_start,
        "speakers_count": len(config.get_enabled_speakers()),
        "is_running": app._is_running,
        "account": config.account[:3] + "***" if config.account else "",
        "mi_did": config.mi_did,
        "setup_completed": config.setup_completed,
    }
    
    return web.json_response(status)


async def handle_health(request: web.Request) -> web.Response:
    """Return the small runtime health snapshot used by Docker and the UI."""
    return web.json_response(build_health_snapshot(request.app["app"]))


async def handle_version(request: web.Request) -> web.Response:
    """Check for the latest GitHub release, compared against the running build."""
    app = request.app["app"]
    force = request.query.get("force") == "1"
    checker = getattr(app, "version_checker", None)
    if checker is None:
        return web.json_response({
            "current_version": __version__,
            "latest_version": None,
            "url": None,
            "update_available": False,
            "error": "Version checker unavailable",
        })
    info = await checker.check(force=force)
    return web.json_response(info)


async def handle_log_stream(request: web.Request) -> web.StreamResponse:
    """Stream live log records to the browser over Server-Sent Events."""
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await response.prepare(request)

    buffer = get_log_buffer()
    # A per-connection queue receives new records as they arrive.
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    buffer.subscribe(queue)

    try:
        # Send the current backlog first.
        for record in buffer.snapshot():
            await response.write(
                f"data: {json.dumps(record, ensure_ascii=False)}\n\n".encode("utf-8")
            )

        # Then stream new records until the client disconnects.
        while True:
            try:
                record = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                # Heartbeat keeps proxies/browsers from dropping idle streams.
                await response.write(b": keep-alive\n\n")
                continue
            await response.write(
                f"data: {json.dumps(record, ensure_ascii=False)}\n\n".encode("utf-8")
            )
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        buffer.unsubscribe(queue)

    return response


async def handle_diagnostics(request: web.Request) -> web.Response:
    """Return a zip archive containing logs and redacted configuration."""
    app = request.app["app"]
    bundle = build_diagnostics_bundle(app)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    return web.Response(
        body=bundle.getvalue(),
        headers={
            "Content-Type": "application/zip",
            "Content-Disposition": (
                f'attachment; filename="miairx-diagnostics-{timestamp}.zip"'
            ),
        },
    )


async def handle_qr_start(request: web.Request) -> web.Response:
    """Start a Xiaomi QR-code login session and return the QR image."""
    app = request.app["app"]
    try:
        result = await app.qr_login.start()
        return web.json_response({"success": True, **result})
    except Exception as exc:  # noqa: BLE001 - surface as a clean error payload
        log.error(f"QR login start failed: {exc}")
        return web.json_response(
            {"success": False, "error": f"获取二维码失败: {exc}"},
            status=500,
        )


async def handle_qr_poll(request: web.Request) -> web.Response:
    """Poll a QR login session; persist credentials and hot-reload on success."""
    app = request.app["app"]
    session_id = request.query.get("session_id", "")
    if not session_id:
        return web.json_response(
            {"success": False, "state": "failed", "message": "缺少 session_id"},
            status=400,
        )

    result = await app.qr_login.poll(session_id)

    if result.get("state") == STATE_CONFIRMED:
        # Never leak the cookie back to the client.
        cookie = result.pop("cookie", None)
        user_id = result.get("user_id", "")

        config = request.app["config"]
        config_store = request.app["config_store"]
        config.cookie = cookie or ""
        config.account = ""
        config.password = ""
        await config_store.save(config)

        # Re-authenticate and rebuild renderers with the new credentials.
        try:
            await app.reload_after_config_change({"cookie", "account", "password"})
        except Exception as exc:  # noqa: BLE001 - reload failure must not 500 the poll
            log.error(f"Reload after QR login failed: {exc}")

        return web.json_response({
            "success": True,
            "state": STATE_CONFIRMED,
            "message": "登录成功，服务已更新",
            "user_id": user_id,
        })

    return web.json_response({"success": True, **result})


async def handle_get_config(request: web.Request) -> web.Response:
    """Handle get configuration request."""
    config = request.app["config"]
    
    # Return config without sensitive data
    config_data = {
        "account": config.account,
        "password": "***" if config.password else "",
        "mi_did": config.mi_did,
        "cookie": "***" if config.cookie else "",
        "hostname": config.hostname,
        "dlna_port": config.dlna_port,
        "web_port": config.web_port,
        "airplay_port_start": config.airplay_port_start,
        "verbose": config.verbose,
        "auto_resume_on_interrupt": config.auto_resume_on_interrupt,
        "resume_delay_seconds": config.resume_delay_seconds,
        "default_volume": config.default_volume,
        "follow_device_volume": config.follow_device_volume,
        "auto_restart": config.auto_restart,
        "web_password": "***" if config.web_password else "",
        "setup_completed": config.setup_completed,
    }
    
    return web.json_response(config_data)


async def handle_save_config(request: web.Request) -> web.Response:
    """Handle save configuration request."""
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("Configuration payload must be a JSON object")

        config = request.app["config"]
        config_store = request.app["config_store"]
        main_app = request.app.get("app")

        allowed_fields = {
            "account", "password", "mi_did", "cookie", "hostname",
            "dlna_port", "web_port", "airplay_port_start", "verbose",
            "auto_resume_on_interrupt", "resume_delay_seconds",
            "default_volume", "follow_device_volume", "auto_restart",
            "web_password",
            "setup_completed",
        }
        unknown_fields = set(data) - allowed_fields
        if unknown_fields:
            raise ValueError(
                "Unknown configuration fields: " + ", ".join(sorted(unknown_fields))
            )

        # Masked values returned by GET /api/config mean "leave unchanged".
        updates = dict(data)
        for field in ("password", "cookie", "web_password"):
            if updates.get(field) == "***":
                updates.pop(field)

        candidate_data = config.model_dump()
        candidate_data.update(updates)

        # Preserve per-speaker metadata for DIDs that remain configured and
        # create clean entries only for newly added devices.
        if "mi_did" in updates and updates["mi_did"] != config.mi_did:
            dids = [did.strip() for did in str(updates["mi_did"]).split(",") if did.strip()]
            candidate_data["speakers"] = {
                did: config.speakers.get(did, {"did": did}) for did in dids
            }

        # AppConfig is the single source of truth for coercion, ranges and
        # cross-field port-layout constraints. The live object is untouched
        # until the complete candidate has validated and persisted.
        candidate = AppConfig.model_validate(candidate_data)
        changed = {
            field
            for field in allowed_fields
            if getattr(config, field) != getattr(candidate, field)
        }
        password_changed = "web_password" in changed

        await config_store.save(candidate)

        # Application components retain a reference to the original config
        # object, so replace its validated state only after persistence works.
        config.__dict__.update(candidate.__dict__)
        config.__pydantic_fields_set__ = candidate.__pydantic_fields_set__.copy()

        # Hot-reload the affected service components so the change takes
        # effect without a manual restart.
        restart_required = False
        if main_app and hasattr(main_app, "reload_after_config_change"):
            restart_required = await main_app.reload_after_config_change(changed)

        response = web.json_response({
            "success": True,
            "message": "Configuration saved successfully",
            "restart_required": restart_required,
            "reauth_required": password_changed and bool(config.web_password),
        })

        # A management-password change invalidates every existing signed
        # session. Explicitly expire the current browser's cookie as well;
        # clients must authenticate again with the new password.
        if password_changed:
            response.del_cookie(_COOKIE_NAME)

        return response

    except (ValidationError, TypeError, ValueError) as e:
        log.error(f"Failed to save config: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        log.error(f"Failed to save config: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_speakers(request: web.Request) -> web.Response:
    """Handle speakers API endpoint."""
    config = request.app["config"]
    app = request.app["app"]
    cached_health = getattr(app, "_speaker_health", {})
    
    speakers = []
    for did, speaker in config.speakers.items():
        speakers.append({
            "did": did,
            "name": speaker.name,
            "hardware": speaker.hardware,
            "enabled": speaker.enabled,
            "udn": speaker.udn,
            "device_id": speaker.device_id,
            "status": cached_health.get(did, {}).get("status", "unknown"),
        })
    
    return web.json_response(speakers)


async def handle_devices(request: web.Request) -> web.Response:
    """Handle devices API endpoint."""
    app = request.app["app"]
    
    devices = await app.get_all_devices()
    auth_error = _xiaomi_status_error(app, devices)
    if auth_error:
        return auth_error
    return web.json_response(devices)


async def handle_discover_speakers(request: web.Request) -> web.Response:
    """Auto-discover smart speakers and return them for one-click selection."""
    app = request.app["app"]
    speakers = await app.discover_speakers()
    auth_error = _xiaomi_status_error(app, speakers)
    if auth_error:
        return auth_error
    return web.json_response(speakers)


def _xiaomi_status_error(app, result: list[dict]) -> web.Response | None:
    """Surface account failures when a Xiaomi list request returned nothing."""
    if result or not getattr(app, "auth", None):
        return None
    status = app.auth.login_status()
    messages = {
        "not_configured": (400, "尚未配置小米账号，请先扫码登录。"),
        "expired": (401, "小米登录已失效，请重新扫码登录。"),
        "network_error": (503, "连接小米服务时发生网络错误，请检查网络后重试。"),
        "service_unavailable": (503, "小米服务暂时不可用，请稍后重试。"),
    }
    if status not in messages:
        return None
    http_status, message = messages[status]
    return web.json_response(
        {"success": False, "xiaomi_status": status, "error": message},
        status=http_status,
    )


async def handle_play(request: web.Request) -> web.Response:
    """Handle play request."""
    try:
        data = await request.json()
        did = data.get("did")
        url = data.get("url")
        
        if not did or not url:
            return web.json_response(
                {
                    "success": False,
                    "error_code": PlaybackErrorCode.UNSUPPORTED_MEDIA,
                    "error": PLAYBACK_ERROR_MESSAGES[PlaybackErrorCode.UNSUPPORTED_MEDIA],
                },
                status=400,
            )

        parsed = urlparse(str(url))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return _playback_error_response(PlaybackErrorCode.UNSUPPORTED_MEDIA, 400)
        try:
            source_ip = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            source_ip = None
        if parsed.hostname.lower() == "localhost" or (source_ip and source_ip.is_loopback):
            return _playback_error_response(
                PlaybackErrorCode.NETWORK_CONFIGURATION_ERROR,
                400,
            )
        
        app = request.app["app"]
        controller = app.speaker_manager.get_controller_by_did(did)
        
        if not controller:
            return _playback_error_response(PlaybackErrorCode.SPEAKER_UNAVAILABLE, 404)

        auth = getattr(app, "auth", None)
        if auth and auth.login_status() == "expired":
            return _playback_error_response(PlaybackErrorCode.XIAOMI_AUTH_EXPIRED, 401)
        speaker_health = getattr(app, "_speaker_health", {}).get(did, {})
        if speaker_health.get("status") == "offline":
            return _playback_error_response(PlaybackErrorCode.SPEAKER_UNAVAILABLE, 503)
        
        result = await controller.play_url(url)
        if not result:
            return _playback_error_response(PlaybackErrorCode.MINA_REQUEST_FAILED, 502)
        return web.json_response({"success": True})
    except Exception as e:
        log.error(f"Play error: {e}")
        return _playback_error_response(classify_playback_exception(e), 502)


def _playback_error_response(
    code: PlaybackErrorCode,
    status: int,
) -> web.Response:
    return web.json_response(
        {
            "success": False,
            "error_code": code,
            "error": PLAYBACK_ERROR_MESSAGES[code],
        },
        status=status,
    )


async def handle_pause(request: web.Request) -> web.Response:
    """Handle pause request."""
    try:
        data = await request.json()
        did = data.get("did")
        
        if not did:
            return web.json_response(
                {"success": False, "error": "Missing did"},
                status=400,
            )
        
        app = request.app["app"]
        controller = app.speaker_manager.get_controller_by_did(did)
        
        if not controller:
            return web.json_response(
                {"success": False, "error": f"Speaker {did} not found"},
                status=404,
            )
        
        result = await controller.pause()
        return web.json_response({"success": result})
    except Exception as e:
        log.error(f"Pause error: {e}")
        return web.json_response(
            {"success": False, "error": str(e)},
            status=500,
        )


async def handle_stop(request: web.Request) -> web.Response:
    """Handle stop request."""
    try:
        data = await request.json()
        did = data.get("did")
        
        if not did:
            return web.json_response(
                {"success": False, "error": "Missing did"},
                status=400,
            )
        
        app = request.app["app"]
        controller = app.speaker_manager.get_controller_by_did(did)
        
        if not controller:
            return web.json_response(
                {"success": False, "error": f"Speaker {did} not found"},
                status=404,
            )
        
        result = await controller.stop()
        return web.json_response({"success": result})
    except Exception as e:
        log.error(f"Stop error: {e}")
        return web.json_response(
            {"success": False, "error": str(e)},
            status=500,
        )


async def handle_volume(request: web.Request) -> web.Response:
    """Handle volume request."""
    try:
        command = VolumeRequest.model_validate(await request.json())
        did = command.did
        
        app = request.app["app"]
        controller = app.speaker_manager.get_controller_by_did(did)
        
        if not controller:
            return web.json_response(
                {"success": False, "error": f"Speaker {did} not found"},
                status=404,
            )
        
        result = await controller.set_volume(command.volume)
        return web.json_response({"success": result})
    except ValidationError as e:
        return web.json_response(
            {"success": False, "error": "Invalid volume request", "details": e.errors()},
            status=400,
        )
    except Exception as e:
        log.error(f"Volume error: {e}")
        return web.json_response(
            {"success": False, "error": str(e)},
            status=500,
        )


async def handle_get_positions(request: web.Request) -> web.Response:
    """Get playback positions for all active renderers."""
    app = request.app["app"]
    result = {}

    for udn, renderer in app.renderers.items():
        if renderer.did:
            position = renderer._get_elapsed_time()
            duration = renderer._track_duration
            state = renderer.transport_state or "no_media"
            result[renderer.did] = {
                "position": round(position, 1),
                "duration": round(duration, 1),
                "state": state,
            }

    return web.json_response({"positions": result})


async def handle_seek(request: web.Request) -> web.Response:
    """Seek to position for a renderer."""
    try:
        command = SeekRequest.model_validate(await request.json())
        did = command.did
        position = command.position

        app = request.app["app"]
        udn = app._did_to_udn.get(did)
        if not udn or udn not in app.renderers:
            return web.json_response({"error": "Renderer not found"}, status=404)

        renderer = app.renderers[udn]
        if renderer._track_duration > 0 and position > renderer._track_duration:
            return web.json_response(
                {"success": False, "error": "Seek position exceeds track duration"},
                status=400,
            )

        # Format position in seconds to HH:MM:SS for DLNA REL_TIME
        hours = int(position // 3600)
        minutes = int((position % 3600) // 60)
        seconds = int(position % 60)
        target = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        success = await renderer.seek("REL_TIME", target)
        return web.json_response({"success": success, "position": position})
    except ValidationError as e:
        return web.json_response(
            {"success": False, "error": "Invalid seek request", "details": e.errors()},
            status=400,
        )
    except Exception as e:
        log.error(f"Seek error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)
