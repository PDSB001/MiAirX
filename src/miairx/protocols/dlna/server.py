"""DLNA HTTP server for MiAirX"""

import asyncio
import logging
import secrets
import socket
import time
from typing import Optional

import aiohttp
from aiohttp import web

from miairx.config.models import AppConfig
from miairx.media.buffer import MediaBuffer
from miairx.protocols.dlna.eventing import EventManager
from miairx.protocols.dlna.renderer import DlnaRenderer
from miairx.protocols.dlna.soap import SoapHandler, parse_soap_action, parse_soap_body
from miairx.protocols.dlna.templates import (
    AVTRANSPORT_SCPD,
    CONNECTION_MANAGER_SCPD,
    RENDERING_CONTROL_SCPD,
    device_description_xml,
)

log = logging.getLogger(__name__)


class DlnaHttpServer:
    """DLNA HTTP server for handling SOAP requests and device descriptions."""

    def __init__(self, hostname: str, dlna_port: int, config: AppConfig):
        self.hostname = hostname
        self.dlna_port = dlna_port
        self.config = config
        self.renderers: dict[str, DlnaRenderer] = {}  # udn -> renderer
        self.event_managers: dict[str, EventManager] = {}  # udn -> event_manager
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        
        # Media proxy system
        self._media_buffers: dict[str, MediaBuffer] = {}  # buffer_id -> MediaBuffer
        self._proxy_tokens: dict[str, tuple[str, str]] = {}  # token -> (buffer_id, udn)
        self._buffer_to_token: dict[str, str] = {}  # buffer_id -> token (O(1) reverse lookup)
        self._url_to_buffer: dict[str, str] = {}  # remote_url -> buffer_id
        self._proxy_session: Optional[aiohttp.ClientSession] = None
        self._gc_task: Optional[asyncio.Task] = None  # Buffer garbage collector

    def register_renderer(self, renderer: DlnaRenderer) -> None:
        """Register a renderer."""
        self.renderers[renderer.udn] = renderer

        # Create event managers for each service
        self.event_managers[renderer.udn] = EventManager(f"AVTransport_{renderer.udn}")

        # Inject callbacks into renderer (like original project)
        renderer.event_manager = self.event_managers[renderer.udn]
        renderer.proxy_url_func = self.create_proxy_url
        renderer.seek_url_func = self.create_seek_url
        renderer.pre_buffer_func = self.start_buffering

        log.info(f"Registered DLNA renderer: {renderer.friendly_name}")

    _UA = (
        "Mozilla/5.0 (Linux; Android 12) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    )

    def _get_proxy_session(self) -> aiohttp.ClientSession:
        """Get or create persistent HTTP session for proxy."""
        if not self._proxy_session or self._proxy_session.closed:
            connector = aiohttp.TCPConnector(
                family=socket.AF_INET,
                limit=50,
                ttl_dns_cache=300,
            )
            self._proxy_session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_read=120),
                headers={"User-Agent": self._UA},
                auto_decompress=False,
            )
        return self._proxy_session

    def create_proxy_url(self, remote_url: str, udn: str) -> str:
        """Create a proxy URL for the given remote URL (O(1) lookup)."""
        # Check if we already have a buffer for this URL
        if remote_url in self._url_to_buffer:
            buffer_id = self._url_to_buffer[remote_url]
            if buffer_id in self._media_buffers:
                # A pre-buffered URL has no token yet. Attach one to the
                # existing buffer instead of starting a duplicate download.
                token = self._buffer_to_token.get(buffer_id)
                if not token:
                    token = secrets.token_urlsafe(16)
                    self._buffer_to_token[buffer_id] = token
                    self._proxy_tokens[token] = (buffer_id, udn)
                return f"http://{self.hostname}:{self.dlna_port}/media/{token}"

            # Drop a stale reverse mapping before creating a fresh buffer.
            self._url_to_buffer.pop(remote_url, None)
        
        # Create new buffer and token
        buffer_id = secrets.token_urlsafe(16)
        token = secrets.token_urlsafe(16)
        
        buffer = MediaBuffer(remote_url)
        self._media_buffers[buffer_id] = buffer
        self._proxy_tokens[token] = (buffer_id, udn)
        self._buffer_to_token[buffer_id] = token
        self._url_to_buffer[remote_url] = buffer_id
        
        # Start download
        session = self._get_proxy_session()
        asyncio.create_task(buffer.start_download(session))
        
        proxy_url = f"http://{self.hostname}:{self.dlna_port}/media/{token}"
        log.info(f"Created proxy URL: {proxy_url}")
        return proxy_url

    def start_buffering(self, remote_url: str) -> None:
        """Start buffering a remote URL."""
        if remote_url in self._url_to_buffer:
            return  # Already buffering
        
        buffer_id = secrets.token_urlsafe(16)
        buffer = MediaBuffer(remote_url)
        self._media_buffers[buffer_id] = buffer
        self._url_to_buffer[remote_url] = buffer_id
        
        # Start download
        session = self._get_proxy_session()
        asyncio.create_task(buffer.start_download(session))
        log.info(f"Started buffering: {remote_url}")

    async def create_seek_url(
        self, original_url: str, seek_seconds: float, duration: float, udn: str = ""
    ) -> Optional[str]:
        """Create a seek URL for resuming playback from a specific position."""
        buffer_id = self._url_to_buffer.get(original_url)
        buf = None
        
        # If buffer not found, try to create new one
        if not buffer_id:
            log.info(f"Seek: Buffer not found, creating new one...")
            buffer_id = secrets.token_urlsafe(16)
            buf = MediaBuffer(original_url)
            self._media_buffers[buffer_id] = buf
            self._url_to_buffer[original_url] = buffer_id
            # Start download
            session = self._get_proxy_session()
            asyncio.create_task(buf.start_download(session))
            log.info(f"Seek: Started new buffer download")
        else:
            buf = self._media_buffers.get(buffer_id)
        
        if not buf or buf.is_error:
            log.warning(f"Seek: Buffer invalid or error")
            return None
        
        # Wait for download to complete (max 15 seconds)
        if not buf.is_complete:
            log.info(f"Seek: Waiting for buffer to complete...")
            try:
                await asyncio.wait_for(buf.wait_ready(), timeout=15.0)
            except asyncio.TimeoutError:
                log.warning(f"Seek: Buffer wait timeout")
                return None
        
        if len(buf.data) == 0:
            log.warning(f"Seek: Buffer is empty")
            return None
        
        if duration <= 0 or seek_seconds < 0:
            log.warning(f"Seek: Invalid time parameters {seek_seconds}/{duration}")
            return None
        
        if seek_seconds >= duration:
            log.warning(f"Seek: Time out of range {seek_seconds}/{duration}")
            return None
        
        # Calculate seek ratio
        seek_ratio = seek_seconds / duration
        log.info(f"Seek: {seek_seconds:.1f}/{duration:.1f}s, ratio={seek_ratio:.3f}")
        
        # Try FFmpeg seek first (most reliable)
        seeked_data = await self._ffmpeg_seek(buf.data, seek_seconds, buf.content_type)
        
        # Fallback: format-aware seek
        if seeked_data is None:
            seeked_data = self._format_seek(buf.data, seek_ratio, buf.content_type)
        
        if seeked_data is None or len(seeked_data) == 0:
            log.warning(f"Seek: Failed to generate seeked audio data")
            return None
        
        # Create new buffer with seeked data
        seek_buf = MediaBuffer(original_url)
        seek_buf.data = seeked_data
        seek_buf.content_type = buf.content_type
        seek_buf.is_complete = True
        seek_buf._complete_event.set()
        
        seek_bid = secrets.token_urlsafe(16)
        self._media_buffers[seek_bid] = seek_buf
        
        token = secrets.token_urlsafe(16)
        self._proxy_tokens[token] = (seek_bid, udn)
        self._buffer_to_token[seek_bid] = token
        url = f"http://{self.hostname}:{self.dlna_port}/media/{token}"
        
        log.info(f"Seek: Audio ready: {len(seeked_data)} bytes (original {len(buf.data)}, seek {seek_seconds:.1f}/{duration:.1f}s)")
        return url

    async def _ffmpeg_seek(self, data: bytes, seconds: float, content_type: str) -> Optional[bytes]:
        """Seek using FFmpeg (piped stdin/stdout, no disk I/O)."""
        import shutil

        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            return None

        try:
            process = await asyncio.create_subprocess_exec(
                ffmpeg_path,
                "-y",
                "-ss", str(seconds),
                "-i", "pipe:0",           # Read from stdin (no temp file)
                "-c", "copy",
                "pipe:1",                  # Write to stdout (no temp file)
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=data),
                timeout=30.0,
            )

            if process.returncode != 0:
                log.warning(f"FFmpeg seek failed: {stderr.decode()[:200]}")
                return None

            return stdout

        except asyncio.TimeoutError:
            log.warning("FFmpeg seek timeout")
            try:
                process.kill()
            except Exception:
                pass
            return None
        except Exception as e:
            log.error(f"FFmpeg seek error: {e}")
            return None

    def _format_seek(self, data: bytes, ratio: float, content_type: str) -> Optional[bytes]:
        """Format-aware seek (fallback when FFmpeg is not available)."""
        try:
            # Simple seek: calculate byte position
            seek_pos = int(len(data) * ratio)
            
            # Align to frame boundary (approximate)
            # For MP3: look for sync word (0xFF 0xFB/0xF3/0xF2)
            # For other formats: just use the calculated position
            
            if "mpeg" in content_type or "mp3" in content_type:
                # Find nearest MP3 sync word
                for i in range(seek_pos, min(seek_pos + 4096, len(data) - 1)):
                    if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
                        seek_pos = i
                        break
            
            return data[seek_pos:]
            
        except Exception as e:
            log.error(f"Format seek error: {e}")
            return None

    async def _gc_buffers(self) -> None:
        """Periodic buffer garbage collection.

        Every 60s, clean up buffers that haven't been accessed for 300s.
        Prevents unbounded memory growth when many songs are played.
        """
        while True:
            try:
                await asyncio.sleep(60)

                now = time.time()
                expired_bids = []

                for bid, buf in self._media_buffers.items():
                    if buf.is_expired(max_age=300):
                        expired_bids.append(bid)

                for bid in expired_bids:
                    buf = self._media_buffers.pop(bid, None)
                    if buf:
                        buf.cancel()
                        buf.cleanup()
                    self._buffer_to_token.pop(bid, None)

                # Clean proxy_tokens pointing to expired buffers
                expired_tokens = [
                    t for t, (bid, _) in self._proxy_tokens.items()
                    if bid not in self._media_buffers
                ]
                for t in expired_tokens:
                    self._proxy_tokens.pop(t, None)

                # Clean url_to_buffer for expired buffers
                expired_urls = [
                    url for url, bid in self._url_to_buffer.items()
                    if bid not in self._media_buffers
                ]
                for url in expired_urls:
                    self._url_to_buffer.pop(url, None)

                if expired_bids:
                    log.warning(
                        f"Buffer GC: cleaned {len(expired_bids)} buffers, "
                        f"{len(self._media_buffers)} remaining"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Buffer GC error: {e}")

    async def start(self) -> None:
        """Start HTTP server and buffer garbage collector."""
        app = web.Application()
        app.router.add_route("*", "/device/{udn}/{path:.*}", self._handle_device_request)
        app.router.add_route("*", "/media/{token}", self._handle_media_request)
        app.router.add_route("*", "/{path:.*}", self._handle_request)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", self.dlna_port)
        await self._site.start()

        # Start buffer GC
        self._gc_task = asyncio.create_task(self._gc_buffers())

        log.warning(f"DLNA HTTP server started on {self.hostname}:{self.dlna_port}")

    async def stop(self) -> None:
        """Stop HTTP server and buffer GC."""
        # Cancel buffer GC
        if self._gc_task:
            self._gc_task.cancel()
            try:
                await self._gc_task
            except asyncio.CancelledError:
                pass
            self._gc_task = None

        # Close all event managers
        for manager in self.event_managers.values():
            await manager.close()

        # Close proxy session
        if self._proxy_session and not self._proxy_session.closed:
            await self._proxy_session.close()

        if self._site:
            await self._site.stop()
            self._site = None

        if self._runner:
            await self._runner.cleanup()
            self._runner = None

        log.warning("DLNA HTTP server stopped")

    async def _handle_device_request(self, request: web.Request) -> web.Response:
        """Handle device-specific requests."""
        udn = request.match_info["udn"]
        path = request.match_info["path"]

        renderer = self.renderers.get(udn)
        if not renderer:
            return web.Response(status=404, text="Device not found")

        # Device description
        if path == "description.xml":
            xml = device_description_xml(udn, renderer.friendly_name)
            return web.Response(
                text=xml,
                content_type="text/xml",
            )

        # Service SCPD
        if path == "AVTransport.xml":
            return web.Response(
                text=AVTRANSPORT_SCPD,
                content_type="text/xml",
            )
        if path == "RenderingControl.xml":
            return web.Response(
                text=RENDERING_CONTROL_SCPD,
                content_type="text/xml",
            )
        if path == "ConnectionManager.xml":
            return web.Response(
                text=CONNECTION_MANAGER_SCPD,
                content_type="text/xml",
            )

        # SOAP control
        if path.endswith("/control"):
            return await self._handle_soap(request, renderer)

        # Event subscription
        if path.endswith("/event"):
            return await self._handle_event(request, renderer)

        return web.Response(status=404, text="Not found")

    async def _handle_soap(self, request: web.Request, renderer: DlnaRenderer) -> web.Response:
        """Handle SOAP request."""
        soap_action = request.headers.get("SOAPAction", "")
        if not soap_action:
            return web.Response(status=400, text="Missing SOAPAction header")

        service_urn, action = parse_soap_action(soap_action)
        if not action:
            return web.Response(status=400, text="Invalid SOAPAction")

        body = await request.text()
        params = parse_soap_body(body)

        response_xml, status = await SoapHandler.handle_request(
            renderer, service_urn, action, params
        )

        return web.Response(
            text=response_xml,
            status=status,
            content_type="text/xml",
        )

    async def _handle_event(self, request: web.Request, renderer: DlnaRenderer) -> web.Response:
        """Handle event subscription request."""
        if request.method == "SUBSCRIBE":
            callback = request.headers.get("Callback", "")
            if not callback:
                return web.Response(status=400, text="Missing Callback header")

            # Extract URL from angle brackets
            if callback.startswith("<") and callback.endswith(">"):
                callback = callback[1:-1]

            timeout_str = request.headers.get("Timeout", "Second-1800")
            try:
                timeout = int(timeout_str.replace("Second-", ""))
            except ValueError:
                timeout = 1800

            manager = self.event_managers.get(renderer.udn)
            if not manager:
                return web.Response(status=500, text="Event manager not found")

            # Check if this is a renewal (has SID header)
            existing_sid = request.headers.get("SID", "")
            if existing_sid:
                # Renewal
                success = manager.renew(existing_sid, timeout)
                if success:
                    return web.Response(
                        status=200,
                        headers={
                            "SID": existing_sid,
                            "TIMEOUT": f"Second-{timeout}",
                        },
                    )
                return web.Response(status=412, text="Invalid SID")
            else:
                # New subscription
                sid = manager.subscribe(callback, timeout)
                
                # Reset volume initialization flag (like original project)
                renderer._volume_initialized = False
                
                # Send initial event in background (like original project)
                asyncio.create_task(self._send_initial_event(manager, sid, renderer))
                
                return web.Response(
                    status=200,
                    headers={
                        "SID": sid,
                        "TIMEOUT": f"Second-{timeout}",
                    },
                )

        elif request.method == "UNSUBSCRIBE":
            sid = request.headers.get("SID", "")
            if not sid:
                return web.Response(status=400, text="Missing SID header")

            manager = self.event_managers.get(renderer.udn)
            if not manager:
                return web.Response(status=500, text="Event manager not found")

            success = manager.unsubscribe(sid)
            if success:
                return web.Response(status=200)
            return web.Response(status=412, text="Invalid SID")

        return web.Response(status=405, text="Method not allowed")

    async def _send_initial_event(self, manager: EventManager, sid: str, renderer: DlnaRenderer) -> None:
        """Send initial event after subscription (background task)."""
        from miairx.protocols.dlna.eventing import build_last_change_event
        
        sub = manager._subscriptions.get(sid)
        if not sub:
            return
        
        # Build initial event with full state
        event_xml = build_last_change_event(
            transport_state=renderer.transport_state,
            volume=renderer.volume,
        )
        
        try:
            await manager._send_notify(sub, event_xml)
        except Exception as e:
            log.debug(f"Initial event failed for {sid}: {e}")

    async def _handle_media_request(self, request: web.Request) -> web.StreamResponse:
        """Handle media requests without waiting for a full-track download."""
        token = request.match_info.get("token", "")

        # Find buffer for this token
        if token not in self._proxy_tokens:
            return web.Response(status=404, text="Not found")

        buffer_id, udn = self._proxy_tokens[token]
        buffer = self._media_buffers.get(buffer_id)

        if not buffer:
            return web.Response(status=404, text="Buffer not found")

        if buffer.is_passthrough:
            return await self._handle_passthrough_request(request, buffer)

        # Only wait for upstream metadata. Small tracks continue buffering in
        # the background while their available bytes are relayed to the
        # speaker, which removes the full-download delay before first sound.
        if not buffer.is_complete and not buffer.is_error:
            success = await buffer.wait_headers(timeout=10)
            if not success:
                if buffer.is_error:
                    return web.Response(status=502, text=buffer.error_message)
                return web.Response(status=504, text="Upstream header timeout")

        if buffer.is_passthrough:
            return await self._handle_passthrough_request(request, buffer)

        if buffer.is_error:
            return web.Response(status=502, text=buffer.error_message)

        return await self._handle_buffered_stream_request(request, buffer)

    @staticmethod
    def _parse_byte_range(range_header: str, total_size: int) -> tuple[int, int]:
        """Parse a single HTTP byte range against a known total size."""
        if not range_header.startswith("bytes=") or "," in range_header:
            raise ValueError("unsupported range")

        range_spec = range_header[6:].strip()
        start_str, end_str = range_spec.split("-", maxsplit=1)

        if not start_str:
            suffix_length = int(end_str)
            if suffix_length <= 0:
                raise ValueError("invalid suffix range")
            start = max(0, total_size - suffix_length)
            end = total_size - 1
        else:
            start = int(start_str)
            end = int(end_str) if end_str else total_size - 1

        if start < 0 or start >= total_size or end < start:
            raise ValueError("range not satisfiable")
        return start, min(end, total_size - 1)

    async def _handle_buffered_stream_request(
        self, request: web.Request, buffer: MediaBuffer
    ) -> web.StreamResponse:
        """Relay buffered media progressively while the upstream download runs."""
        total_size = buffer.content_length or len(buffer.data)
        if total_size <= 0:
            return web.Response(status=502, text="Upstream content length unavailable")

        range_header = request.headers.get("Range", "")
        status = 200
        start = 0
        end = total_size - 1
        headers = {
            "Content-Type": buffer.content_type or "application/octet-stream",
            "Accept-Ranges": "bytes",
        }

        if range_header:
            try:
                start, end = self._parse_byte_range(range_header, total_size)
            except (TypeError, ValueError):
                return web.Response(
                    status=416,
                    headers={"Content-Range": f"bytes */{total_size}"},
                    text="Range not satisfiable",
                )
            status = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"

        headers["Content-Length"] = str(end - start + 1)
        response = web.StreamResponse(status=status, headers=headers)
        await response.prepare(request)

        if request.method == "HEAD":
            await response.write_eof()
            return response

        position = start
        try:
            while position <= end:
                chunk = await buffer.read_available(
                    position,
                    min(64 * 1024, end - position + 1),
                )
                if chunk:
                    await response.write(chunk)
                    position += len(chunk)
                    continue

                if buffer.is_error:
                    log.warning(
                        "Media download failed while streaming %s: %s",
                        buffer.url[:80],
                        buffer.error_message,
                    )
                    response.force_close()
                    return response
                if buffer.is_complete:
                    break

                if not await buffer.wait_for_data(position, timeout=120):
                    log.warning("Media stream stalled: %s", buffer.url[:80])
                    response.force_close()
                    return response

            await response.write_eof()
            return response
        except ConnectionResetError:
            log.debug("Buffered media streaming client disconnected")
            return response

    async def _handle_passthrough_request(
        self, request: web.Request, buffer: MediaBuffer
    ) -> web.StreamResponse:
        """Stream oversized media from its source without buffering it in RAM."""
        upstream_request_headers = {}
        for name in ("Range", "If-Range"):
            value = request.headers.get(name)
            if value:
                upstream_request_headers[name] = value

        response: Optional[web.StreamResponse] = None
        try:
            session = self._get_proxy_session()
            method = "HEAD" if request.method == "HEAD" else "GET"
            async with session.request(
                method,
                buffer.url,
                headers=upstream_request_headers,
                allow_redirects=True,
            ) as upstream:
                response_headers = {}
                for name in (
                    "Content-Type",
                    "Content-Length",
                    "Content-Range",
                    "Accept-Ranges",
                    "Content-Encoding",
                    "ETag",
                    "Last-Modified",
                ):
                    value = upstream.headers.get(name)
                    if value is not None:
                        response_headers[name] = value

                response_headers.setdefault(
                    "Content-Type", buffer.content_type or "application/octet-stream"
                )
                response_headers.setdefault("Accept-Ranges", "bytes")

                response = web.StreamResponse(
                    status=upstream.status,
                    reason=upstream.reason,
                    headers=response_headers,
                )
                await response.prepare(request)

                if method != "HEAD":
                    async for chunk in upstream.content.iter_chunked(64 * 1024):
                        await response.write(chunk)

                await response.write_eof()
                return response
        except asyncio.CancelledError:
            raise
        except ConnectionResetError:
            log.debug("Oversized media streaming client disconnected")
            if response is not None:
                return response
            raise
        except Exception as e:
            log.error(f"Oversized media streaming failed: {e}")
            if response is not None:
                response.force_close()
                return response
            return web.Response(status=502, text="Upstream media request failed")

    def _handle_range_request(
        self,
        request: web.Request,
        data_view: memoryview,
        content_type: str,
        range_header: str,
    ) -> web.Response:
        """Handle Range request (zero-copy via memoryview)."""
        try:
            total_size = len(data_view)

            # Parse Range header
            range_spec = range_header.replace("bytes=", "").strip()
            start_str, end_str = range_spec.split("-")

            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else total_size - 1

            # Clamp to available data
            end = min(end, total_size - 1)

            if start > end or start >= total_size:
                return web.Response(status=416, text="Range not satisfiable")

            # memoryview slice is zero-copy — just a view, no allocation
            chunk = data_view[start:end + 1]
            content_length = end - start + 1

            headers = {
                "Content-Type": content_type,
                "Content-Length": str(content_length),
                "Content-Range": f"bytes {start}-{end}/{total_size}",
                "Accept-Ranges": "bytes",
            }

            return web.Response(
                body=chunk,
                status=206,
                headers=headers,
            )

        except Exception as e:
            log.error(f"Range request error: {e}")
            return web.Response(status=400, text="Invalid range")

    async def _handle_request(self, request: web.Request) -> web.Response:
        """Handle generic requests."""
        return web.Response(status=404, text="Not found")
