"""Media proxy for streaming audio in MiAirX"""

import asyncio
import logging
import secrets
from typing import Optional

from aiohttp import web

from miairx.media.buffer import MediaBuffer

log = logging.getLogger(__name__)


class MediaProxy:
    """HTTP proxy for streaming media with Range support."""

    def __init__(self, hostname: str, port: int):
        """Initialize media proxy.
        
        Args:
            hostname: Server hostname
            port: Server port
        """
        self.hostname = hostname
        self.port = port
        self._buffers: dict[str, MediaBuffer] = {}  # token -> buffer
        self._url_to_token: dict[str, str] = {}  # url -> token
        self._lock = asyncio.Lock()

    def register_buffer(self, url: str, buffer: MediaBuffer) -> str:
        """Register a media buffer and return proxy URL.
        
        Args:
            url: Original media URL
            buffer: MediaBuffer instance
            
        Returns:
            Proxy URL
        """
        token = secrets.token_urlsafe(16)

        # Remove existing buffer for this URL
        if url in self._url_to_token:
            old_token = self._url_to_token.pop(url)
            self._buffers.pop(old_token, None)

        self._buffers[token] = buffer
        self._url_to_token[url] = token

        proxy_url = f"http://{self.hostname}:{self.port}/media/{token}"
        log.info(f"Registered proxy: {proxy_url}")
        return proxy_url

    def unregister_buffer(self, token: str) -> None:
        """Unregister a media buffer."""
        buffer = self._buffers.pop(token, None)
        if buffer:
            buffer.cancel()
            buffer.cleanup()

    def get_buffer(self, token: str) -> Optional[MediaBuffer]:
        """Get buffer by token."""
        return self._buffers.get(token)

    async def handle_request(self, request: web.Request) -> web.StreamResponse:
        """Handle media proxy request with Range support."""
        token = request.match_info.get("token", "")
        buffer = self.get_buffer(token)

        if not buffer:
            return web.Response(status=404, text="Not found")

        # Wait for download to start
        if not buffer.data and not buffer.is_error:
            await asyncio.sleep(0.1)

        if buffer.is_error:
            return web.Response(status=502, text=buffer.error_message)

        # Handle Range request
        range_header = request.headers.get("Range", "")
        if range_header:
            return await self._handle_range_request(request, buffer, range_header)

        # Full request
        if not buffer.is_complete:
            await buffer.wait_ready()

        if buffer.is_error:
            return web.Response(status=502, text=buffer.error_message)

        headers = {
            "Content-Type": buffer.content_type,
            "Content-Length": str(len(buffer.data)),
            "Accept-Ranges": "bytes",
        }

        response = web.StreamResponse(status=200, headers=headers)
        await response.prepare(request)
        await response.write(bytes(buffer.data))
        await response.write_eof()

        return response

    async def _handle_range_request(
        self, request: web.Request, buffer: MediaBuffer, range_header: str
    ) -> web.StreamResponse:
        """Handle Range request."""
        try:
            # Parse Range header
            range_spec = range_header.replace("bytes=", "").strip()
            start_str, end_str = range_spec.split("-")

            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else None

            # Wait for enough data
            if end is not None:
                required_size = end + 1
            else:
                required_size = start + 1

            while len(buffer.data) < required_size:
                if buffer.is_error:
                    return web.Response(status=502, text=buffer.error_message)
                if buffer.is_complete:
                    break
                await asyncio.sleep(0.05)

            # Get actual end position
            if end is None:
                end = len(buffer.data) - 1

            # Clamp to available data
            end = min(end, len(buffer.data) - 1)

            if start > end:
                return web.Response(status=416, text="Range not satisfiable")

            # Read data
            data = await buffer.read_range(start, end)
            content_length = end - start + 1

            headers = {
                "Content-Type": buffer.content_type,
                "Content-Length": str(content_length),
                "Content-Range": f"bytes {start}-{end}/{len(buffer.data)}",
                "Accept-Ranges": "bytes",
            }

            response = web.StreamResponse(status=206, headers=headers)
            await response.prepare(request)
            await response.write(data)
            await response.write_eof()

            return response

        except Exception as e:
            log.error(f"Range request error: {e}")
            return web.Response(status=400, text="Invalid range")

    async def cleanup(self) -> None:
        """Cleanup all buffers."""
        for token in list(self._buffers.keys()):
            self.unregister_buffer(token)
