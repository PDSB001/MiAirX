"""Tests for media buffering and proxy reuse."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from miairx.config.models import AppConfig
from miairx.media.buffer import MediaBuffer
from miairx.protocols.dlna.server import DlnaHttpServer


class _FakeContent:
    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    status = 200
    headers: dict[str, str] = {}

    def __init__(self, chunks: list[bytes]):
        self.content = _FakeContent(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _FakeSession:
    def __init__(self, chunks: list[bytes]):
        self._response = _FakeResponse(chunks)

    def get(self, _url: str):
        return self._response


@pytest.mark.asyncio
async def test_streaming_download_enforces_memory_limit():
    """Chunked responses cannot bypass max_memory."""
    buffer = MediaBuffer("http://example.com/audio", max_memory=5)

    await buffer._download(_FakeSession([b"1234", b"56"]))

    assert buffer.is_error is True
    assert buffer.is_complete is False
    assert buffer.error_message == "File too large"
    assert await buffer.wait_ready(timeout=0.01) is False


@pytest.mark.asyncio
async def test_prebuffer_is_reused_when_proxy_url_is_created(monkeypatch):
    """SetAVTransportURI pre-buffering must not download the URL twice."""
    server = DlnaHttpServer("192.168.1.10", 8200, AppConfig())
    start_download = AsyncMock()
    monkeypatch.setattr(MediaBuffer, "start_download", start_download)
    monkeypatch.setattr(server, "_get_proxy_session", MagicMock(return_value=MagicMock()))

    remote_url = "http://example.com/song.mp3"
    server.start_buffering(remote_url)
    await asyncio.sleep(0)

    proxy_url = server.create_proxy_url(remote_url, "uuid:test")

    assert proxy_url.startswith("http://192.168.1.10:8200/media/")
    assert len(server._media_buffers) == 1
    assert len(server._proxy_tokens) == 1
    start_download.assert_awaited_once()
