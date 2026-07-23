"""Audio format detection for MiAirX"""

import logging
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


class AudioFormat(str, Enum):
    """Supported audio formats."""
    MP3 = "mp3"
    FLAC = "flac"
    WAV = "wav"
    AAC = "aac"
    OGG = "ogg"
    M4A = "m4a"
    WMA = "wma"
    APE = "ape"
    UNKNOWN = "unknown"


# Magic bytes for format detection
FORMAT_MAGIC = {
    AudioFormat.FLAC: b"fLaC",
    AudioFormat.WAV: b"RIFF",
    AudioFormat.OGG: b"OggS",
    AudioFormat.APE: b"MAC ",
}

# MP3 sync words (multiple variants)
MP3_SYNC_BYTES = [
    b"\xff\xfb",  # MPEG1 Layer 3
    b"\xff\xf3",  # MPEG2 Layer 3
    b"\xff\xf2",  # MPEG2.5 Layer 3
]

# AAC sync bytes
AAC_SYNC_BYTES = [
    b"\xff\xf1",  # AAC ADTS
    b"\xff\xf9",  # AAC ADTS
]

# ID3 tag (MP3 with ID3 header)
ID3_MAGIC = b"ID3"

# M4A/MP4 ftyp box
M4A_MAGIC = b"ftyp"


def detect_audio_format(data: bytes, filename: str = "") -> AudioFormat:
    """Detect audio format from data header or filename.
    
    Args:
        data: Audio data (first few bytes)
        filename: Optional filename for extension-based detection
        
    Returns:
        Detected AudioFormat
    """
    # Try magic bytes first
    if data:
        # Check for ID3 tag (MP3)
        if data[:3] == ID3_MAGIC:
            return AudioFormat.MP3

        # Check for ftyp box (M4A/MP4)
        if len(data) >= 4 and data[4:8] == M4A_MAGIC:
            return AudioFormat.M4A

        # Check MP3 sync bytes
        for sync in MP3_SYNC_BYTES:
            if data[:len(sync)] == sync:
                return AudioFormat.MP3

        # Check AAC sync bytes
        for sync in AAC_SYNC_BYTES:
            if data[:len(sync)] == sync:
                return AudioFormat.AAC

        # Check other magic bytes
        for fmt, magic in FORMAT_MAGIC.items():
            if data[:len(magic)] == magic:
                return fmt

    # Try filename extension
    if filename:
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        ext_map = {
            "mp3": AudioFormat.MP3,
            "flac": AudioFormat.FLAC,
            "wav": AudioFormat.WAV,
            "aac": AudioFormat.AAC,
            "ogg": AudioFormat.OGG,
            "oga": AudioFormat.OGG,
            "m4a": AudioFormat.M4A,
            "mp4": AudioFormat.M4A,
            "wma": AudioFormat.WMA,
            "ape": AudioFormat.APE,
        }
        if ext in ext_map:
            return ext_map[ext]

    return AudioFormat.UNKNOWN


def get_content_type(format: AudioFormat) -> str:
    """Get MIME content type for audio format."""
    content_types = {
        AudioFormat.MP3: "audio/mpeg",
        AudioFormat.FLAC: "audio/flac",
        AudioFormat.WAV: "audio/wav",
        AudioFormat.AAC: "audio/aac",
        AudioFormat.OGG: "audio/ogg",
        AudioFormat.M4A: "audio/mp4",
        AudioFormat.WMA: "audio/x-ms-wma",
        AudioFormat.APE: "audio/ape",
    }
    return content_types.get(format, "audio/mpeg")


def get_file_extension(format: AudioFormat) -> str:
    """Get file extension for audio format."""
    extensions = {
        AudioFormat.MP3: ".mp3",
        AudioFormat.FLAC: ".flac",
        AudioFormat.WAV: ".wav",
        AudioFormat.AAC: ".aac",
        AudioFormat.OGG: ".ogg",
        AudioFormat.M4A: ".m4a",
        AudioFormat.WMA: ".wma",
        AudioFormat.APE: ".ape",
    }
    return extensions.get(format, ".mp3")


def is_lossless(format: AudioFormat) -> bool:
    """Check if format is lossless."""
    return format in {AudioFormat.FLAC, AudioFormat.WAV, AudioFormat.APE}


def needs_transcoding(format: AudioFormat, target_hardware: str) -> bool:
    """Check if format needs transcoding for specific hardware.
    
    Args:
        format: Audio format
        target_hardware: Hardware model string
        
    Returns:
        True if transcoding is needed
    """
    from miairx.const import NEED_USE_PLAY_MUSIC_API

    # Hardware that doesn't support lossless formats
    NON_LOSSLESS_HARDWARE = {"L05B", "L05C", "LX06", "L16A"}

    if target_hardware not in NON_LOSSLESS_HARDWARE:
        return False

    if is_lossless(format):
        return True

    return False
