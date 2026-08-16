"""Unit tests for version checking helpers."""

import pytest

from miairx.version_check import is_newer, parse_version


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
