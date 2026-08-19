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
# Use the HTML "latest" page instead of the REST API: the API enforces a
# 60 req/hour unauthenticated rate limit per IP, which is exhausted almost
# immediately on shared/NAT egress IPs. The HTML page 302-redirects to
# /releases/tag/<version> with no such quota.
_LATEST_URL = f"https://github.com/{_REPO}/releases/latest"
_CACHE_TTL_SECONDS = 6 * 3600  # 6 hours
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)
_USER_AGENT = "MiAirX-version-check/1.0"


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


def parse_tag_from_location(location: str) -> str:
    """Extract the version tag from a GitHub release URL.

    ``https://github.com/PDSB001/MiAirX/releases/tag/v1.5.0`` -> ``v1.5.0``.
    """
    marker = "/releases/tag/"
    if marker in location:
        return location.rsplit("/", 1)[-1].strip()
    return ""


class VersionChecker:
    """Cached, non-blocking checker for the latest GitHub release."""

    def __init__(self, session: aiohttp.ClientSession, repo: str = _REPO):
        self._session = session
        self._url = f"https://github.com/{repo}/releases/latest"
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
                allow_redirects=False,
                headers={"User-Agent": _USER_AGENT},
            ) as response:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location", "")
                    latest = parse_tag_from_location(location)
                    if latest:
                        base["latest_version"] = latest
                        base["url"] = location
                        base["update_available"] = is_newer(latest, __version__)
                    else:
                        base["error"] = f"无法解析重定向地址: {location}"
                    return base
                if response.status == 404:
                    base["error"] = "仓库不存在或尚未发布任何版本"
                    return base
                base["error"] = f"GitHub 返回 HTTP {response.status}"
                return base
        except Exception as exc:  # noqa: BLE001 - network/parse failures are non-fatal
            log.debug("Version check failed: %s", exc)
            base["error"] = str(exc)
            return base
