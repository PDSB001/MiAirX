"""Unit tests for version checking helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from miairx.version_check import (
    VersionChecker,
    is_newer,
    parse_tag_from_location,
    parse_version,
)


class TestParseTagFromLocation:
    def test_extracts_tag(self):
        assert parse_tag_from_location(
            "https://github.com/PDSB001/MiAirX/releases/tag/v1.5.0"
        ) == "v1.5.0"

    def test_no_tag_returns_empty(self):
        assert parse_tag_from_location("https://github.com/PDSB001/MiAirX") == ""


class TestVersionCheckerFetch:
    @pytest.mark.asyncio
    async def test_follows_redirect_for_version(self):
        session = MagicMock()
        resp = AsyncMock()
        resp.status = 302
        resp.headers = {"Location": "https://github.com/PDSB001/MiAirX/releases/tag/v1.6.0"}
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=resp)

        checker = VersionChecker(session)
        result = await checker._fetch()

        assert result["latest_version"] == "v1.6.0"
        assert result["update_available"] is True
        assert result["error"] is None
        # Must hit the HTML latest page, not the API.
        assert "api.github.com" not in session.get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_404_marks_error(self):
        session = MagicMock()
        resp = AsyncMock()
        resp.status = 404
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=resp)

        checker = VersionChecker(session)
        result = await checker._fetch()

        assert result["error"]
        assert result["update_available"] is False


class TestParseVersion:
    def test_simple(self):
        assert parse_version("1.5.0") == (1, 5, 0)

    def test_strips_v_prefix(self):
        assert parse_version("v1.6.0") == (1, 6, 0)

    def test_missing_components(self):
        assert parse_version("1.6") == (1, 6, 0)
        assert parse_version("2") == (2, 0, 0)

    def test_invalid(self):
        assert parse_version("") == (0, 0, 0)
        assert parse_version("abc") == (0, 0, 0)

    def test_prerelease_suffix_ignored(self):
        assert parse_version("1.6.0-beta") == (1, 6, 0)


class TestIsNewer:
    def test_newer_detected(self):
        assert is_newer("1.6.0", "1.5.0")

    def test_same_version_not_newer(self):
        assert not is_newer("1.5.0", "1.5.0")

    def test_older_not_newer(self):
        assert not is_newer("1.4.0", "1.5.0")

    def test_minor_bump(self):
        assert is_newer("1.10.0", "1.9.0")

    def test_v_prefix(self):
        assert is_newer("v1.6.0", "1.5.0")
