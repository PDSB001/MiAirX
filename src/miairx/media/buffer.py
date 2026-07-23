"""Media buffer for async download in MiAirX"""

import asyncio
import logging
import time
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)


class MediaBuffer:
    """Async media download buffer with memory management."""

    def __init__(self, url: str, max_memory: int = 200 * 1024 * 1024):
        """Initialize media buffer.
        
        Args:
            url: Media URL to download
            max_memory: Maximum memory usage in bytes (default 200MB)
        """
        self.url = url
        self.max_memory = max_memory
        self.data: bytearray = bytearray()
        self.content_length: int = 0
        self.content_type: str = ""
        self.is_complete: bool = False
        self.is_error: bool = False
        self.error_message: str = ""
        self.created_at: float = time.time()
        self.last_accessed: float = time.time()
        self._download_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
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

                self.content_length = int(response.headers.get("Content-Length", 0))
                self.content_type = response.headers.get("Content-Type", "audio/mpeg")

                # Check memory limit
                if self.content_length > self.max_memory:
                    log.warning(f"File too large: {self.content_length} > {self.max_memory}")
                    self.is_error = True
                    self.error_message = "File too large"
                    return

                # Download data
                async for chunk in response.content.iter_chunked(8192):
                    async with self._lock:
                        self.data.extend(chunk)
                        self.last_accessed = time.time()

                self.is_complete = True
                self._complete_event.set()
                log.info(f"Download complete: {len(self.data)} bytes")

        except Exception as e:
            self.is_error = True
            self.error_message = str(e)
            log.error(f"Download failed: {e}")

    async def wait_ready(self, timeout: float = 120.0) -> bool:
        """Wait for download to complete.
        
        Args:
            timeout: Maximum wait time in seconds
            
        Returns:
            True if download completed successfully
        """
        try:
            await asyncio.wait_for(self._complete_event.wait(), timeout=timeout)
            return True
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
