import pytest

from miairx.auth.errors import TokenExpiredError
from miairx.core.playback_errors import PlaybackErrorCode, classify_playback_exception


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TokenExpiredError("expired"), PlaybackErrorCode.XIAOMI_AUTH_EXPIRED),
        (RuntimeError("source returned HTTP 404"), PlaybackErrorCode.SOURCE_UNAVAILABLE),
        (RuntimeError("speaker is offline"), PlaybackErrorCode.SPEAKER_UNAVAILABLE),
        (RuntimeError("MiNA ubus error"), PlaybackErrorCode.MINA_REQUEST_FAILED),
        (RuntimeError("FFmpeg transcode failed"), PlaybackErrorCode.TRANSCODE_FAILED),
        (RuntimeError("unsupported codec"), PlaybackErrorCode.UNSUPPORTED_MEDIA),
        (RuntimeError("localhost network configuration"), PlaybackErrorCode.NETWORK_CONFIGURATION_ERROR),
    ],
)
def test_playback_error_categories(error, expected):
    assert classify_playback_exception(error) == expected
