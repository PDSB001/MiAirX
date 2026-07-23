"""HTTP audio stream server for AirPlay in MiAirX"""

import asyncio
import logging
import queue
import struct
import subprocess
import threading
import time
from typing import Optional

from aiohttp import web

log = logging.getLogger(__name__)

# Queue parameters
_QUEUE_MAXSIZE = 100


class AudioStreamServer:
    """HTTP audio stream server for AirPlay.
    
    Receives PCM audio data and serves it via HTTP for Xiaomi speakers.
    Supports WAV and MP3 output formats.
    """

    def __init__(self, hostname: str, port: int = 0, audio_format: str = "wav"):
        self.hostname = hostname
        self.port = port
        self._audio_format = audio_format
        self._app = web.Application()
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

        # Audio data queue
        self._audio_queue: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._sample_rate = 44100
        self._channels = 2
        self._sample_width = 2  # 16-bit
        self._active = False
        self._abort = False
        self._session_id = int(time.time())

        self._setup_routes()

    def _setup_routes(self):
        if self._audio_format == "mp3":
            self._app.router.add_get("/airplay/stream.mp3", self._handle_stream_mp3)
        else:
            self._app.router.add_get("/airplay/stream.wav", self._handle_stream_wav)

    @property
    def stream_url(self) -> str:
        ext = "mp3" if self._audio_format == "mp3" else "wav"
        return f"http://{self.hostname}:{self.port}/airplay/stream.{ext}?sid={self._session_id}"

    async def start(self):
        """Start the HTTP server."""
        self._runner = web.AppRunner(self._app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await self._site.start()
        self.port = self._site._server.sockets[0].getsockname()[1]
        log.info(f"AirPlay audio stream server: http://{self.hostname}:{self.port} (format: {self._audio_format})")

    async def stop(self):
        """Stop the HTTP server."""
        self._active = False
        try:
            self._audio_queue.put_nowait(None)
        except queue.Full:
            pass
        if self._runner:
            await self._runner.cleanup()

    def set_audio_params(self, sample_rate: int, channels: int, sample_width: int = 2):
        """Set audio parameters."""
        self._sample_rate = sample_rate
        self._channels = channels
        self._sample_width = sample_width

    def start_streaming(self):
        """Start accepting audio data."""
        self._active = True
        self._abort = False
        self._session_id = int(time.time())
        # Clear queue
        while True:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
        log.info(f"Audio stream: started (format: {self._audio_format})")

    def stop_streaming(self):
        """Stop accepting audio data."""
        self._active = False
        try:
            self._audio_queue.put_nowait(None)
        except queue.Full:
            pass
        log.info("Audio stream: stopped")

    def abort_streaming(self):
        """Abort current streaming session."""
        self._abort = True
        self._active = False
        try:
            self._audio_queue.put_nowait(None)
        except queue.Full:
            pass
        log.info("Audio stream: aborted")

    def write_audio(self, data: bytes):
        """Write PCM audio data to the queue."""
        if not self._active or self._abort:
            return
        try:
            self._audio_queue.put_nowait(data)
        except queue.Full:
            # Drop oldest data
            try:
                self._audio_queue.get_nowait()
                self._audio_queue.put_nowait(data)
            except (queue.Empty, queue.Full):
                pass

    async def _handle_stream_wav(self, request: web.Request) -> web.StreamResponse:
        """Handle WAV stream request."""
        log.info("WAV stream client connected")

        headers = {
            "Content-Type": "audio/wav",
            "Cache-Control": "no-cache",
            "Connection": "close",
        }

        response = web.StreamResponse(status=200, headers=headers)
        await response.prepare(request)

        # Write WAV header
        wav_header = self._build_wav_header(0)  # Unknown length
        await response.write(wav_header)

        # Stream audio data
        silence_count = 0
        while self._active and not self._abort:
            try:
                data = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._audio_queue.get(timeout=1.0)
                )
                if data is None:
                    break
                await response.write(data)
                silence_count = 0
            except queue.Empty:
                # Send silence to keep connection alive
                silence_count += 1
                if silence_count >= 3:
                    silence = b'\x00' * (self._sample_rate * self._channels * self._sample_width // 10)
                    await response.write(silence)
                    silence_count = 0

        return response

    async def _handle_stream_mp3(self, request: web.Request) -> web.StreamResponse:
        """Handle MP3 stream request (via ffmpeg transcoding)."""
        log.info("MP3 stream client connected")

        headers = {
            "Content-Type": "audio/mpeg",
            "Cache-Control": "no-cache",
            "Connection": "close",
        }

        response = web.StreamResponse(status=200, headers=headers)
        await response.prepare(request)

        # Start ffmpeg process for MP3 transcoding
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "s16le",
            "-ar", str(self._sample_rate),
            "-ac", str(self._channels),
            "-i", "pipe:0",
            "-acodec", "libmp3lame",
            "-b:a", "128k",
            "-f", "mp3",
            "pipe:1",
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Feed audio data to ffmpeg
            async def feed_audio():
                while self._active and not self._abort:
                    try:
                        data = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: self._audio_queue.get(timeout=1.0)
                        )
                        if data is None:
                            break
                        process.stdin.write(data)
                        await process.stdin.drain()
                    except queue.Empty:
                        pass
                    except Exception as e:
                        log.error(f"Audio feed error: {e}")
                        break
                process.stdin.close()

            # Read MP3 output from ffmpeg
            async def read_output():
                while True:
                    data = await process.stdout.read(4096)
                    if not data:
                        break
                    try:
                        await response.write(data)
                    except Exception:
                        break

            # Run both tasks
            await asyncio.gather(feed_audio(), read_output())

        except Exception as e:
            log.error(f"MP3 transcoding error: {e}")

        return response

    def _build_wav_header(self, data_size: int) -> bytes:
        """Build WAV file header."""
        if data_size == 0:
            data_size = 0xFFFFFFFF  # Unknown length

        byte_rate = self._sample_rate * self._channels * self._sample_width
        block_align = self._channels * self._sample_width

        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            data_size + 36,  # ChunkSize
            b"WAVE",
            b"fmt ",
            16,  # Subchunk1Size
            1,  # AudioFormat (PCM)
            self._channels,
            self._sample_rate,
            byte_rate,
            block_align,
            self._sample_width * 8,  # BitsPerSample
            b"data",
            data_size,
        )
        return header
