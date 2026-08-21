"""Tests for media buffering and proxy reuse."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

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

    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None):
        self.content = _FakeContent(chunks)
        self.headers = (
            {"Content-Length": str(sum(map(len, chunks)))}
            if headers is None
            else headers
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _FakeSession:
    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None):
        self._response = _FakeResponse(chunks, headers)

    def get(self, _url: str):
        return self._response


class _SlowContent:
    def __init__(self):
        self.first_chunk_consumed = asyncio.Event()
        self.release_final_chunk = asyncio.Event()

    async def iter_chunked(self, _size: int):
        yield b"1234"
        self.first_chunk_consumed.set()
        await self.release_final_chunk.wait()
        yield b"567890"


class _SlowResponse(_FakeResponse):
    def __init__(self, content: _SlowContent):
        self.content = content
        self.headers = {
            "Content-Length": "10",
            "Content-Type": "audio/mpeg",
        }


class _SlowSession:
    def __init__(self, content: _SlowContent):
        self._response = _SlowResponse(content)

    def get(self, _url: str):
        return self._response


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=0-", (0, 9)),
        ("bytes=2-5", (2, 5)),
        ("bytes=-4", (6, 9)),
    ],
)
def test_parse_byte_range(header, expected):
    assert DlnaHttpServer._parse_byte_range(header, 10) == expected


@pytest.mark.asyncio
async def test_large_download_switches_to_streaming_passthrough():
    """Large responses are proxied instead of being rejected or held in RAM."""
    buffer = MediaBuffer("http://example.com/audio", max_memory=5)

    await buffer._download(_FakeSession([b"1234", b"56"]))

    assert buffer.is_passthrough is True
    assert buffer.is_error is False
    assert buffer.is_complete is False
    assert buffer.data == bytearray()
    assert await buffer.wait_ready(timeout=0.01) is True


@pytest.mark.asyncio
async def test_incorrect_small_content_length_cannot_fill_memory():
    """A lying upstream is cleared once the hard in-memory limit is crossed."""
    buffer = MediaBuffer("http://example.com/audio", max_memory=5)

    await buffer._download(
        _FakeSession([b"1234", b"56"], headers={"Content-Length": "4"})
    )

    assert buffer.is_passthrough is True
    assert buffer.data == bytearray()


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"Content-Length": "invalid"}])
async def test_unknown_length_download_uses_streaming_passthrough(headers):
    """Unknown-size responses start without waiting for an arbitrary limit."""
    buffer = MediaBuffer("http://example.com/audio")

    await buffer._download(_FakeSession([b"audio"], headers=headers))

    assert buffer.is_passthrough is True
    assert buffer.data == bytearray()
    assert await buffer.wait_ready(timeout=0.01) is True


@pytest.mark.asyncio
async def test_streaming_passthrough_preserves_range_requests():
    """Oversized media proxy forwards byte ranges and streams the response."""
    seen_range = None

    async def upstream_handler(request: web.Request) -> web.Response:
        nonlocal seen_range
        seen_range = request.headers.get("Range")
        return web.Response(
            status=206,
            body=b"2345",
            headers={
                "Content-Type": "audio/mpeg",
                "Content-Range": "bytes 2-5/10",
                "Accept-Ranges": "bytes",
            },
        )

    upstream_app = web.Application()
    upstream_app.router.add_get("/audio", upstream_handler)
    upstream = TestServer(upstream_app, host="127.0.0.1")
    await upstream.start_server()

    server = DlnaHttpServer("127.0.0.1", 8200, AppConfig())
    buffer = MediaBuffer(str(upstream.make_url("/audio")))
    buffer.is_passthrough = True
    buffer.content_type = "audio/mpeg"
    server._media_buffers["buffer"] = buffer
    server._proxy_tokens["token"] = ("buffer", "uuid:test")

    proxy_app = web.Application()
    proxy_app.router.add_route("*", "/media/{token}", server._handle_media_request)
    proxy = TestClient(TestServer(proxy_app, host="127.0.0.1"))
    await proxy.start_server()

    try:
        response = await proxy.get("/media/token", headers={"Range": "bytes=2-5"})
        assert response.status == 206
        assert response.headers["Content-Range"] == "bytes 2-5/10"
        assert await response.read() == b"2345"
        assert seen_range == "bytes=2-5"
    finally:
        await proxy.close()
        await upstream.close()
        if server._proxy_session:
            await server._proxy_session.close()


@pytest.mark.asyncio
async def test_small_media_streams_before_full_download_completes():
    """First audio bytes are relayed while the rest is still downloading."""
    slow_content = _SlowContent()
    buffer = MediaBuffer("http://example.com/audio")
    download_task = asyncio.create_task(buffer._download(_SlowSession(slow_content)))
    await asyncio.wait_for(slow_content.first_chunk_consumed.wait(), timeout=1)

    server = DlnaHttpServer("127.0.0.1", 8200, AppConfig())
    server._media_buffers["buffer"] = buffer
    server._proxy_tokens["token"] = ("buffer", "uuid:test")

    proxy_app = web.Application()
    proxy_app.router.add_route("*", "/media/{token}", server._handle_media_request)
    proxy = TestClient(TestServer(proxy_app, host="127.0.0.1"))
    await proxy.start_server()

    try:
        response = await proxy.get("/media/token")
        first_chunk = await asyncio.wait_for(response.content.readexactly(4), timeout=1)

        assert first_chunk == b"1234"
        assert buffer.is_complete is False

        slow_content.release_final_chunk.set()
        assert await response.read() == b"567890"
        await asyncio.wait_for(download_task, timeout=1)
        assert buffer.is_complete is True
    finally:
        slow_content.release_final_chunk.set()
        await proxy.close()
        await asyncio.gather(download_task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("range_header", "expected_range", "expected_body"),
    [
        ("bytes=5-", "bytes 5-9/10", b"56789"),
        ("bytes=-4", "bytes 6-9/10", b"6789"),
    ],
)
async def test_buffered_range_response_has_real_length(
    range_header, expected_range, expected_body
):
    buffer = MediaBuffer("http://example.com/audio")
    buffer.data = bytearray(b"0123456789")
    buffer.content_length = 10
    buffer.content_type = "audio/mpeg"
    buffer.is_complete = True

    server = DlnaHttpServer("127.0.0.1", 8200, AppConfig())
    server._media_buffers["buffer"] = buffer
    server._proxy_tokens["token"] = ("buffer", "uuid:test")
    proxy_app = web.Application()
    proxy_app.router.add_route("*", "/media/{token}", server._handle_media_request)
    proxy = TestClient(TestServer(proxy_app, host="127.0.0.1"))
    await proxy.start_server()

    try:
        response = await proxy.get("/media/token", headers={"Range": range_header})
        assert response.status == 206
        assert response.headers["Content-Range"] == expected_range
        assert int(response.headers["Content-Length"]) == len(expected_body)
        assert await response.read() == expected_body
    finally:
        await proxy.close()


@pytest.mark.asyncio
async def test_unsatisfiable_range_returns_total_size():
    buffer = MediaBuffer("http://example.com/audio")
    buffer.data = bytearray(b"0123456789")
    buffer.content_length = 10
    buffer.is_complete = True
    server = DlnaHttpServer("127.0.0.1", 8200, AppConfig())
    server._media_buffers["buffer"] = buffer
    server._proxy_tokens["token"] = ("buffer", "uuid:test")
    proxy_app = web.Application()
    proxy_app.router.add_route("*", "/media/{token}", server._handle_media_request)
    proxy = TestClient(TestServer(proxy_app, host="127.0.0.1"))
    await proxy.start_server()

    try:
        response = await proxy.get("/media/token", headers={"Range": "bytes=10-"})
        assert response.status == 416
        assert response.headers["Content-Range"] == "bytes */10"
    finally:
        await proxy.close()


@pytest.mark.asyncio
async def test_large_passthrough_seek_does_not_load_media_into_memory():
    server = DlnaHttpServer("127.0.0.1", 8200, AppConfig())
    buffer = MediaBuffer("http://example.com/large-audio")
    buffer.is_passthrough = True
    server._url_to_buffer[buffer.url] = "buffer"
    server._media_buffers["buffer"] = buffer

    seek_url = await server.create_seek_url(buffer.url, 30, 300, "uuid:test")

    assert seek_url is None
    assert buffer.data == bytearray()


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
