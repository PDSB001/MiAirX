"""Media buffer for async download in MiAirX"""

import asyncio
import logging
import time
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)


class MediaBuffer:
    """Async media download buffer with memory management."""

    def __init__(
        self,
        url: str,
        max_memory: int = 200 * 1024 * 1024,
        streaming_threshold: int = 32 * 1024 * 1024,
    ):
        """Initialize media buffer.
        
        Args:
            url: Media URL to download
            max_memory: Maximum memory usage in bytes (default 200MB)
            streaming_threshold: Known-size files above this value are streamed
                directly instead of being fully buffered (default 32MB)
        """
        self.url = url
        self.max_memory = max_memory
        self.streaming_threshold = min(streaming_threshold, max_memory)
        self.data: bytearray = bytearray()
        self.content_length: int = 0
        self.content_type: str = ""
        self.is_complete: bool = False
        self.is_passthrough: bool = False
        self.is_error: bool = False
        self.error_message: str = ""
        self.created_at: float = time.time()
        self.last_accessed: float = time.time()
        self._download_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._headers_event = asyncio.Event()
        self._data_event = asyncio.Event()
        self._complete_event = asyncio.Event()

    async def start_download(self, session: aiohttp.ClientSession) -> None:
        """Start downloading the media file."""
        self._download_task = asyncio.create_task(self._download(session))

    async def _download(self, session: aiohttp.ClientSession) -> None:
        """Download the media file."""
        try:
            async with session.get(self.url) as response:
                if response.status != 200:
                    self.is_error = True
                    self.error_message = f"HTTP {response.status}"
                    return

                content_length = response.headers.get("Content-Length", "")
                try:
                    self.content_length = int(content_length)
                except (TypeError, ValueError):
                    self.content_length = 0
                self.content_type = response.headers.get("Content-Type", "audio/mpeg")

                # Unknown-size and large responses should be streamed directly.
                # Fully downloading these before serving delays playback and can
                # exhaust the container's memory.
                if (
                    self.content_length == 0
                    or self.content_length > self.streaming_threshold
                ):
                    self.is_passthrough = True
                    self._headers_event.set()
                    self._data_event.set()
                    log.info(
                        "Using streaming proxy for media with "
                        f"content length {self.content_length or 'unknown'}"
                    )
                    return

                # The proxy can start responding as soon as upstream headers
                # are known. The body continues downloading in the background
                # and is relayed progressively instead of blocking playback
                # until the complete track is buffered.
                self._headers_event.set()

                # Download data. A larger chunk reduces per-iteration lock
                # acquisition and event signalling overhead, letting the
                # pre-buffer (started on SetAVTransportURI) pull more bytes in
                # the gap before the speaker requests the proxy URL, which
                # shortens the time-to-first-sound.
                async for chunk in response.content.iter_chunked(64 * 1024):
                    async with self._lock:
                        if len(self.data) + len(chunk) > self.max_memory:
                            buffered_size = len(self.data) + len(chunk)
                            self.data.clear()
                            self.is_passthrough = True
                            log.info(
                                "Media exceeded memory buffer limit while downloading; "
                                "using streaming proxy: "
                                f"{buffered_size} > {self.max_memory}"
                            )
                            self._data_event.set()
                            return
                        self.data.extend(chunk)
                        self.last_accessed = time.time()
                    self._data_event.set()

                self.is_complete = True
                self._complete_event.set()
                self._data_event.set()
                log.info(f"Download complete: {len(self.data)} bytes")

        except Exception as e:
            self.is_error = True
            self.error_message = str(e)
            log.error(f"Download failed: {e}")
        finally:
            # Wake waiters on both success and failure. Without this, a
            # download that fails after wait_ready() starts blocks until the
            # full timeout even though the error is already known.
            self._headers_event.set()
            self._data_event.set()
            self._complete_event.set()

    async def wait_headers(self, timeout: float = 10.0) -> bool:
        """Wait until upstream response metadata or an error is available."""
        try:
            await asyncio.wait_for(self._headers_event.wait(), timeout=timeout)
            return not self.is_error
        except asyncio.TimeoutError:
            return False

    async def wait_for_data(self, position: int, timeout: float = 120.0) -> bool:
        """Wait until data after ``position`` or a terminal state is available."""

        async def _wait() -> bool:
            while True:
                # Clear before checking state so a writer cannot signal between
                # the state check and the following wait.
                self._data_event.clear()
                async with self._lock:
                    if len(self.data) > position:
                        return True
                    if self.is_complete or self.is_passthrough or self.is_error:
                        return False
                await self._data_event.wait()

        try:
            return await asyncio.wait_for(_wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False

    async def read_available(self, start: int, size: int) -> bytes:
        """Copy up to ``size`` currently buffered bytes starting at ``start``."""
        async with self._lock:
            end = min(len(self.data), start + size)
            if start >= end:
                return b""
            self.last_accessed = time.time()
            return bytes(self.data[start:end])

    async def wait_ready(self, timeout: float = 120.0) -> bool:
        """Wait for download to complete.
        
        Args:
            timeout: Maximum wait time in seconds
            
        Returns:
            True if download completed successfully
        """
        try:
            await asyncio.wait_for(self._complete_event.wait(), timeout=timeout)
            return (self.is_complete or self.is_passthrough) and not self.is_error
        except asyncio.TimeoutError:
            return False

    async def read_range(self, start: int, end: int) -> bytes:
        """Read a range of bytes from the buffer.
        
        Args:
            start: Start byte position
            end: End byte position (inclusive)
            
        Returns:
            Requested bytes
        """
        async with self._lock:
            self.last_accessed = time.time()
            return bytes(self.data[start:end + 1])

    async def get_size(self) -> int:
        """Get current buffer size."""
        async with self._lock:
            return len(self.data)

    def is_expired(self, max_age: float = 3600.0) -> bool:
        """Check if buffer has expired.
        
        Args:
            max_age: Maximum age in seconds
            
        Returns:
            True if buffer has expired
        """
        return time.time() - self.last_accessed > max_age

    def cancel(self) -> None:
        """Cancel the download."""
        if self._download_task and not self._download_task.done():
            self._download_task.cancel()

    def cleanup(self) -> None:
        """Release memory."""
        self.data.clear()
        self.data = bytearray()
