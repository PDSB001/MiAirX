"""Unit tests for audio format detection"""

import pytest

from miairx.media.formats import (
    AudioFormat,
    detect_audio_format,
    get_content_type,
    get_file_extension,
    is_lossless,
)


def test_detect_mp3():
    """Test MP3 detection."""
    # MP3 with sync word
    data = b"\xff\xfb\x90\x00" + b"\x00" * 100
    assert detect_audio_format(data) == AudioFormat.MP3
    
    # MP3 with ID3 header
    data = b"ID3" + b"\x00" * 100
    assert detect_audio_format(data) == AudioFormat.MP3


def test_detect_flac():
    """Test FLAC detection."""
    data = b"fLaC" + b"\x00" * 100
    assert detect_audio_format(data) == AudioFormat.FLAC


def test_detect_wav():
    """Test WAV detection."""
    data = b"RIFF" + b"\x00" * 100
    assert detect_audio_format(data) == AudioFormat.WAV


def test_detect_ogg():
    """Test OGG detection."""
    data = b"OggS" + b"\x00" * 100
    assert detect_audio_format(data) == AudioFormat.OGG


def test_detect_by_filename():
    """Test format detection by filename."""
    assert detect_audio_format(b"", "song.mp3") == AudioFormat.MP3
    assert detect_audio_format(b"", "song.flac") == AudioFormat.FLAC
    assert detect_audio_format(b"", "song.wav") == AudioFormat.WAV
    assert detect_audio_format(b"", "song.ogg") == AudioFormat.OGG
    assert detect_audio_format(b"", "song.m4a") == AudioFormat.M4A


def test_detect_unknown():
    """Test unknown format detection."""
    data = b"\x00\x00\x00\x00"
    assert detect_audio_format(data) == AudioFormat.UNKNOWN
    assert detect_audio_format(b"", "song.xyz") == AudioFormat.UNKNOWN


def test_get_content_type():
    """Test content type mapping."""
    assert get_content_type(AudioFormat.MP3) == "audio/mpeg"
    assert get_content_type(AudioFormat.FLAC) == "audio/flac"
    assert get_content_type(AudioFormat.WAV) == "audio/wav"
    assert get_content_type(AudioFormat.OGG) == "audio/ogg"
    assert get_content_type(AudioFormat.M4A) == "audio/mp4"


def test_get_file_extension():
    """Test file extension mapping."""
    assert get_file_extension(AudioFormat.MP3) == ".mp3"
    assert get_file_extension(AudioFormat.FLAC) == ".flac"
    assert get_file_extension(AudioFormat.WAV) == ".wav"
    assert get_file_extension(AudioFormat.OGG) == ".ogg"
    assert get_file_extension(AudioFormat.M4A) == ".m4a"


def test_is_lossless():
    """Test lossless format detection."""
    assert is_lossless(AudioFormat.FLAC) is True
    assert is_lossless(AudioFormat.WAV) is True
    assert is_lossless(AudioFormat.APE) is True
    assert is_lossless(AudioFormat.MP3) is False
    assert is_lossless(AudioFormat.OGG) is False
