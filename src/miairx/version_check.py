"""Latest-release version check against GitHub.

Queries the GitHub Releases API for the latest published MiAirX release and
compares it with the running version. Results are cached in-memory for a short
window so the management console can refresh without hammering the API, and a
network failure never blocks the status endpoint.
"""

import logging
import time

import aiohttp

from miairx import __version__

log = logging.getLogger(__name__)

_REPO = "PDSB001/MiAirX"
_RELEASES_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"
_CACHE_TTL_SECONDS = 6 * 3600  # 6 hours
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


def parse_version(value: str) -> tuple[int, ...]:
    """Parse a semantic-ish version string into a comparable tuple."""
    cleaned = str(value or "").strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.split("."):
        digits = ""
        for char in chunk:
            if char.isdigit():
                digits += char
            else:
                break
        parts.append(int(digits) if digits else 0)
    # Normalise to at least three components for comparison.
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    """Return True when ``candidate`` is a strictly newer version."""
    return parse_version(candidate) > parse_version(current)


class VersionChecker:
    """Cached, non-blocking checker for the latest GitHub release."""

    def __init__(self, session: aiohttp.ClientSession, repo: str = _REPO):
        self._session = session
        self._url = f"https://api.github.com/repos/{repo}/releases/latest"
        self._cached_at: float = 0.0
        self._cached_result: dict | None = None

    async def check(self, force: bool = False) -> dict:
        """Return the latest release info, using a cached value when fresh.

        The returned dict always contains ``current_version`` and
        ``update_available``; ``latest_version`` and ``url`` are present only
        when a release was successfully retrieved.
        """
        now = time.time()
        if not force and self._cached_result is not None:
            if now - self._cached_at < _CACHE_TTL_SECONDS:
                return self._cached_result

        result = await self._fetch()
        self._cached_at = now
        self._cached_result = result
        return result

    async def _fetch(self) -> dict:
        base = {
            "current_version": __version__,
            "latest_version": None,
            "url": None,
            "update_available": False,
            "error": None,
        }
        try:
            async with self._session.get(
                self._url,
                timeout=_REQUEST_TIMEOUT,
                headers={"Accept": "application/vnd.github+json"},
            ) as response:
                if response.status != 200:
                    base["error"] = f"GitHub API returned {response.status}"
                    return base
                data = await response.json()
        except Exception as exc:  # noqa: BLE001 - network/parse failures are non-fatal
            log.debug("Version check failed: %s", exc)
            base["error"] = str(exc)
            return base

        latest = str(data.get("tag_name") or data.get("name") or "")
        base["latest_version"] = latest
        base["url"] = data.get("html_url") or ""
        base["update_available"] = is_newer(latest, __version__)
        return base
