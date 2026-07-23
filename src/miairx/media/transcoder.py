"""Audio transcoding using FFmpeg for MiAirX"""

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from miairx.media.formats import AudioFormat, get_content_type

log = logging.getLogger(__name__)


class AudioTranscoder:
    """FFmpeg-based audio transcoding."""

    def __init__(self, ffmpeg_path: Optional[str] = None):
        """Initialize transcoder.
        
        Args:
            ffmpeg_path: Path to FFmpeg binary (auto-detect if None)
        """
        self._ffmpeg_path = ffmpeg_path or self._find_ffmpeg()

    @staticmethod
    def _find_ffmpeg() -> Optional[str]:
        """Find FFmpeg binary in system PATH."""
        return shutil.which("ffmpeg")

    @property
    def is_available(self) -> bool:
        """Check if FFmpeg is available."""
        if self._ffmpeg_path is None:
            return False
        return Path(self._ffmpeg_path).exists() or shutil.which(self._ffmpeg_path) is not None

    async def transcode(
        self,
        input_data: bytes,
        input_format: AudioFormat,
        output_format: AudioFormat,
        sample_rate: int = 44100,
        channels: int = 2,
        bitrate: str = "128k",
    ) -> Optional[bytes]:
        """Transcode audio data.
        
        Args:
            input_data: Input audio data
            input_format: Input audio format
            output_format: Output audio format
            sample_rate: Output sample rate
            channels: Output channels
            bitrate: Output bitrate (for lossy formats)
            
        Returns:
            Transcoded audio data, or None on failure
        """
        if not self.is_available:
            log.error("FFmpeg not available")
            return None

        try:
            # Create temp files
            with tempfile.NamedTemporaryFile(suffix=f".{input_format.value}", delete=False) as tmp_in:
                tmp_in.write(input_data)
                tmp_in_path = tmp_in.name

            tmp_out_path = tmp_in_path + f".{output_format.value}"

            # Build FFmpeg command
            cmd = [
                self._ffmpeg_path,
                "-y",
                "-i", tmp_in_path,
                "-ar", str(sample_rate),
                "-ac", str(channels),
            ]

            # Add format-specific options
            if output_format == AudioFormat.MP3:
                cmd.extend(["-acodec", "libmp3lame", "-b:a", bitrate])
            elif output_format == AudioFormat.AAC:
                cmd.extend(["-acodec", "aac", "-b:a", bitrate])
            elif output_format == AudioFormat.WAV:
                cmd.extend(["-acodec", "pcm_s16le"])
            elif output_format == AudioFormat.FLAC:
                cmd.extend(["-acodec", "flac"])
            elif output_format == AudioFormat.OGG:
                cmd.extend(["-acodec", "libvorbis", "-b:a", bitrate])

            cmd.append(tmp_out_path)

            # Run FFmpeg
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                log.warning(f"FFmpeg transcoding failed: {stderr.decode()}")
                return None

            # Read result
            with open(tmp_out_path, "rb") as f:
                result = f.read()

            # Cleanup
            Path(tmp_in_path).unlink(missing_ok=True)
            Path(tmp_out_path).unlink(missing_ok=True)

            log.info(f"Transcoded {input_format.value} -> {output_format.value}: {len(input_data)} -> {len(result)} bytes")
            return result

        except Exception as e:
            log.error(f"Transcoding error: {e}")
            return None

    async def to_wav(
        self,
        input_data: bytes,
        input_format: AudioFormat,
        sample_rate: int = 44100,
        channels: int = 2,
    ) -> Optional[bytes]:
        """Transcode to WAV format.
        
        Args:
            input_data: Input audio data
            input_format: Input audio format
            sample_rate: Output sample rate
            channels: Output channels
            
        Returns:
            WAV audio data, or None on failure
        """
        return await self.transcode(
            input_data,
            input_format,
            AudioFormat.WAV,
            sample_rate=sample_rate,
            channels=channels,
        )

    async def to_mp3(
        self,
        input_data: bytes,
        input_format: AudioFormat,
        sample_rate: int = 44100,
        channels: int = 2,
        bitrate: str = "128k",
    ) -> Optional[bytes]:
        """Transcode to MP3 format.
        
        Args:
            input_data: Input audio data
            input_format: Input audio format
            sample_rate: Output sample rate
            channels: Output channels
            bitrate: Output bitrate
            
        Returns:
            MP3 audio data, or None on failure
        """
        return await self.transcode(
            input_data,
            input_format,
            AudioFormat.MP3,
            sample_rate=sample_rate,
            channels=channels,
            bitrate=bitrate,
        )

    async def convert_file(
        self,
        input_path: str,
        output_path: str,
        output_format: AudioFormat,
        sample_rate: int = 44100,
        channels: int = 2,
        bitrate: str = "128k",
    ) -> bool:
        """Convert audio file.
        
        Args:
            input_path: Input file path
            output_path: Output file path
            output_format: Output format
            sample_rate: Output sample rate
            channels: Output channels
            bitrate: Output bitrate
            
        Returns:
            True on success
        """
        if not self.is_available:
            log.error("FFmpeg not available")
            return False

        try:
            cmd = [
                self._ffmpeg_path,
                "-y",
                "-i", input_path,
                "-ar", str(sample_rate),
                "-ac", str(channels),
            ]

            if output_format == AudioFormat.MP3:
                cmd.extend(["-acodec", "libmp3lame", "-b:a", bitrate])
            elif output_format == AudioFormat.WAV:
                cmd.extend(["-acodec", "pcm_s16le"])
            elif output_format == AudioFormat.FLAC:
                cmd.extend(["-acodec", "flac"])

            cmd.append(output_path)

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                log.warning(f"FFmpeg conversion failed: {stderr.decode()}")
                return False

            return True

        except Exception as e:
            log.error(f"File conversion error: {e}")
            return False
