"""Web application factory for MiAirX"""

import json
import logging
from pathlib import Path

from aiohttp import web

from miairx.config.models import AppConfig
from miairx.config.store import ConfigStore

log = logging.getLogger(__name__)

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
    web_app = web.Application()
    
    # Store references
    web_app["config"] = config
    web_app["app"] = app
    web_app["config_store"] = config_store or ConfigStore(config.conf_path)
    
    # Setup routes
    web_app.router.add_get("/", handle_index)
    web_app.router.add_get("/api/status", handle_status)
    web_app.router.add_get("/api/config", handle_get_config)
    web_app.router.add_post("/api/config", handle_save_config)
    web_app.router.add_get("/api/speakers", handle_speakers)
    web_app.router.add_get("/api/devices", handle_devices)
    web_app.router.add_post("/api/play", handle_play)
    web_app.router.add_post("/api/pause", handle_pause)
    web_app.router.add_post("/api/stop", handle_stop)
    web_app.router.add_post("/api/volume", handle_volume)
    web_app.router.add_get("/api/positions", handle_get_positions)
    web_app.router.add_post("/api/seek", handle_seek)
    web_app.router.add_static("/static/", path=STATIC_DIR, name="static")
    
    return web_app


async def handle_index(request: web.Request) -> web.Response:
    """Handle index page."""
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_status(request: web.Request) -> web.Response:
    """Handle status API endpoint."""
    config = request.app["config"]
    app = request.app["app"]
    
    status = {
        "version": "1.0.0",
        "hostname": config.hostname,
        "dlna_port": config.dlna_port,
        "web_port": config.web_port,
        "speakers_count": len(config.get_enabled_speakers()),
        "is_running": app._is_running,
        "account": config.account[:3] + "***" if config.account else "",
        "mi_did": config.mi_did,
    }
    
    return web.json_response(status)


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
        "verbose": config.verbose,
        "proxy_enabled": config.proxy_enabled,
        "auto_play_on_set_uri": config.auto_play_on_set_uri,
        "auto_resume_on_interrupt": config.auto_resume_on_interrupt,
        "resume_delay_seconds": config.resume_delay_seconds,
        "default_volume": config.default_volume,
        "follow_device_volume": config.follow_device_volume,
        "enable_voice_control": config.enable_voice_control,
        "auto_restart": config.auto_restart,
        "voice_poll_interval": config.voice_poll_interval,
    }
    
    return web.json_response(config_data)


async def handle_save_config(request: web.Request) -> web.Response:
    """Handle save configuration request."""
    try:
        data = await request.json()
        config = request.app["config"]
        config_store = request.app["config_store"]
        
        # Update config fields
        if "account" in data:
            config.account = data["account"]
        if "password" in data and data["password"] != "***":
            config.password = data["password"]
        if "mi_did" in data:
            config.mi_did = data["mi_did"]
            # Rebuild speaker config from new mi_did
            config.speakers = {}
            for did in config.get_did_list():
                config.get_speaker(did)
            # Try to update speaker info from cloud
            try:
                main_app = request.app.get("app")
                if main_app and getattr(main_app, "auth", None):
                    await main_app.auth.update_speakers_info()
            except Exception:
                log.warning("Failed to refresh speaker info after mi_did change")
        if "cookie" in data and data["cookie"] != "***":
            config.cookie = data["cookie"]
        if "hostname" in data:
            config.hostname = data["hostname"]
        if "dlna_port" in data:
            config.dlna_port = int(data["dlna_port"])
        if "web_port" in data:
            config.web_port = int(data["web_port"])
        if "verbose" in data:
            config.verbose = bool(data["verbose"])
        if "proxy_enabled" in data:
            config.proxy_enabled = bool(data["proxy_enabled"])
        if "auto_play_on_set_uri" in data:
            config.auto_play_on_set_uri = bool(data["auto_play_on_set_uri"])
        if "auto_resume_on_interrupt" in data:
            config.auto_resume_on_interrupt = bool(data["auto_resume_on_interrupt"])
        if "resume_delay_seconds" in data:
            config.resume_delay_seconds = int(data["resume_delay_seconds"])
        if "default_volume" in data:
            config.default_volume = int(data["default_volume"])
        if "follow_device_volume" in data:
            config.follow_device_volume = bool(data["follow_device_volume"])
        if "enable_voice_control" in data:
            config.enable_voice_control = bool(data["enable_voice_control"])
        if "auto_restart" in data:
            config.auto_restart = bool(data["auto_restart"])
        if "voice_poll_interval" in data:
            config.voice_poll_interval = int(data["voice_poll_interval"])
        
        # Save config to file
        await config_store.save(config)
        
        return web.json_response({"success": True, "message": "Configuration saved successfully"})
        
    except Exception as e:
        log.error(f"Failed to save config: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=400)


async def handle_speakers(request: web.Request) -> web.Response:
    """Handle speakers API endpoint."""
    config = request.app["config"]
    
    speakers = []
    for did, speaker in config.speakers.items():
        speakers.append({
            "did": did,
            "name": speaker.name,
            "hardware": speaker.hardware,
            "enabled": speaker.enabled,
            "udn": speaker.udn,
            "device_id": speaker.device_id,
        })
    
    return web.json_response(speakers)


async def handle_devices(request: web.Request) -> web.Response:
    """Handle devices API endpoint."""
    app = request.app["app"]
    
    devices = await app.get_all_devices()
    return web.json_response(devices)


async def handle_play(request: web.Request) -> web.Response:
    """Handle play request."""
    try:
        data = await request.json()
        did = data.get("did")
        url = data.get("url")
        
        if not did or not url:
            return web.json_response(
                {"success": False, "error": "Missing did or url"},
                status=400,
            )
        
        app = request.app["app"]
        controller = app.speaker_manager.get_controller_by_did(did)
        
        if not controller:
            return web.json_response(
                {"success": False, "error": f"Speaker {did} not found"},
                status=404,
            )
        
        result = await controller.play_url(url)
        return web.json_response({"success": result})
    except Exception as e:
        log.error(f"Play error: {e}")
        return web.json_response(
            {"success": False, "error": str(e)},
            status=500,
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
        data = await request.json()
        did = data.get("did")
        volume = data.get("volume")
        
        if not did or volume is None:
            return web.json_response(
                {"success": False, "error": "Missing did or volume"},
                status=400,
            )
        
        app = request.app["app"]
        controller = app.speaker_manager.get_controller_by_did(did)
        
        if not controller:
            return web.json_response(
                {"success": False, "error": f"Speaker {did} not found"},
                status=404,
            )
        
        result = await controller.set_volume(int(volume))
        return web.json_response({"success": result})
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
        data = await request.json()
        did = data.get("did", "")
        position = data.get("position", 0)

        if not did:
            return web.json_response({"error": "Missing did"}, status=400)

        app = request.app["app"]
        udn = app._did_to_udn.get(did)
        if not udn or udn not in app.renderers:
            return web.json_response({"error": "Renderer not found"}, status=404)

        renderer = app.renderers[udn]

        # Format position in seconds to HH:MM:SS for DLNA REL_TIME
        hours = int(position // 3600)
        minutes = int((position % 3600) // 60)
        seconds = int(position % 60)
        target = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        await renderer.seek("REL_TIME", target)
        return web.json_response({"success": True, "position": position})
    except Exception as e:
        log.error(f"Seek error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)
