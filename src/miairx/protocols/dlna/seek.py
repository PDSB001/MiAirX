"""Audio seek logic for MiAirX"""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional

from miairx.media.formats import AudioFormat, detect_audio_format

log = logging.getLogger(__name__)


class AudioSeeker:
    """Audio seek with FFmpeg fallback."""

    @staticmethod
    async def ffmpeg_seek(
        data: bytes,
        seconds: float,
        content_type: str,
        ffmpeg_path: str = "ffmpeg",
    ) -> Optional[bytes]:
        """Seek using FFmpeg.
        
        Args:
            data: Audio data
            seconds: Seek position in seconds
            content_type: Content type hint
            ffmpeg_path: Path to FFmpeg binary
            
        Returns:
            Seeked audio data, or None on failure
        """
        try:
            # Create temp files
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp_in:
                tmp_in.write(data)
                tmp_in_path = tmp_in.name

            tmp_out_path = tmp_in_path + ".seeked"

            # Run FFmpeg
            cmd = [
                ffmpeg_path,
                "-y",
                "-ss", str(seconds),
                "-i", tmp_in_path,
                "-c", "copy",
                tmp_out_path,
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                log.warning(f"FFmpeg seek failed: {stderr.decode()}")
                return None

            # Read result
            with open(tmp_out_path, "rb") as f:
                result = f.read()

            # Cleanup
            Path(tmp_in_path).unlink(missing_ok=True)
            Path(tmp_out_path).unlink(missing_ok=True)

            return result

        except Exception as e:
            log.error(f"FFmpeg seek error: {e}")
            return None

    @staticmethod
    def format_seek(data: bytes, ratio: float, format: AudioFormat) -> Optional[bytes]:
        """Seek using format-aware parsing.
        
        Args:
            data: Audio data
            ratio: Seek position as ratio (0.0 to 1.0)
            format: Audio format
            
        Returns:
            Seeked audio data, or None on failure
        """
        try:
            if format == AudioFormat.FLAC:
                return AudioSeeker._seek_flac(data, ratio)
            elif format == AudioFormat.MP3:
                return AudioSeeker._seek_mp3(data, ratio)
            elif format == AudioFormat.WAV:
                return AudioSeeker._seek_wav(data, ratio)
            else:
                return None
        except Exception as e:
            log.error(f"Format seek error: {e}")
            return None

    @staticmethod
    def _seek_flac(data: bytes, ratio: float) -> Optional[bytes]:
        """Seek in FLAC file."""
        # Find FLAC header
        if data[:4] != b"fLaC":
            return None

        # Find first frame sync code
        sync_pos = -1
        for i in range(4, len(data) - 1):
            if data[i] == 0xFF and (data[i + 1] & 0xF8) == 0xF8:
                sync_pos = i
                break

        if sync_pos == -1:
            return None

        # Calculate seek position
        header = data[:sync_pos]
        audio_data = data[sync_pos:]
        seek_pos = int(len(audio_data) * ratio)

        # Align to frame boundary
        for i in range(seek_pos, min(seek_pos + 4096, len(audio_data) - 1)):
            if audio_data[i] == 0xFF and (audio_data[i + 1] & 0xF8) == 0xF8:
                seek_pos = i
                break

        return header + audio_data[seek_pos:]

    @staticmethod
    def _seek_mp3(data: bytes, ratio: float) -> Optional[bytes]:
        """Seek in MP3 file."""
        # Skip ID3v2 header
        header_end = 0
        if data[:3] == b"ID3":
            if len(data) >= 10:
                size_bytes = data[6:10]
                header_end = (
                    (size_bytes[0] << 21)
                    | (size_bytes[1] << 14)
                    | (size_bytes[2] << 7)
                    | size_bytes[3]
                ) + 10

        header = data[:header_end]
        audio_data = data[header_end:]

        # Find first sync frame
        sync_pos = -1
        for i in range(min(4096, len(audio_data) - 1)):
            if audio_data[i] == 0xFF and (audio_data[i + 1] & 0xE0) == 0xE0:
                sync_pos = i
                break

        if sync_pos == -1:
            return None

        audio_data = audio_data[sync_pos:]
        seek_pos = int(len(audio_data) * ratio)

        # Align to frame boundary
        for i in range(seek_pos, min(seek_pos + 4096, len(audio_data) - 1)):
            if audio_data[i] == 0xFF and (audio_data[i + 1] & 0xE0) == 0xE0:
                seek_pos = i
                break

        return header + audio_data[seek_pos:]

    @staticmethod
    def _seek_wav(data: bytes, ratio: float) -> Optional[bytes]:
        """Seek in WAV file."""
        # Find data chunk
        data_pos = data.find(b"data")
        if data_pos == -1:
            return None

        header = data[:data_pos + 8]
        audio_data = data[data_pos + 8:]

        # Calculate seek position
        seek_pos = int(len(audio_data) * ratio)

        # Align to sample boundary (assuming 16-bit stereo)
        seek_pos = (seek_pos // 4) * 4

        return header + audio_data[seek_pos:]
