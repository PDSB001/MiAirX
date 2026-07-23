"""UPnP eventing for DLNA in MiAirX"""

import asyncio
import logging
import time
import uuid
from typing import Optional
from xml.sax.saxutils import escape

import aiohttp

log = logging.getLogger(__name__)


class Subscription:
    """An event subscription."""

    def __init__(self, sid: str, callback_url: str, timeout: int = 1800):
        self.sid = sid
        self.callback_url = callback_url
        self.timeout = timeout
        self.created_at = time.monotonic()
        self.seq: int = 0

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.timeout

    def renew(self, timeout: int = 1800):
        self.timeout = timeout
        self.created_at = time.monotonic()


class EventManager:
    """UPnP event subscription manager."""

    def __init__(self, service_id: str = ""):
        self.service_id = service_id
        self._subscriptions: dict[str, Subscription] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_session(self) -> aiohttp.ClientSession:
        """Get or create persistent HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            )
        return self._session

    def subscribe(self, callback_url: str, timeout: int = 1800) -> str:
        """Create new subscription."""
        sid = f"uuid:{uuid.uuid4()}"
        self._subscriptions[sid] = Subscription(sid, callback_url, timeout)
        log.info(f"Event subscription created: {sid} -> {callback_url}")
        return sid

    def renew(self, sid: str, timeout: int = 1800) -> bool:
        """Renew subscription."""
        if sid in self._subscriptions:
            self._subscriptions[sid].renew(timeout)
            return True
        return False

    def unsubscribe(self, sid: str) -> bool:
        """Remove subscription."""
        if sid in self._subscriptions:
            del self._subscriptions[sid]
            log.info(f"Event subscription removed: {sid}")
            return True
        return False

    def has_subscribers(self) -> bool:
        """Check if there are any active subscribers."""
        return any(not sub.expired for sub in self._subscriptions.values())

    async def notify(self, renderer) -> None:
        """Send notification to all subscribers in parallel (with per-subscriber timeout)."""
        if not self._subscriptions:
            return

        # Build LastChange event
        event_xml = build_last_change_event(
            transport_state=renderer.transport_state,
            volume=renderer.volume,
        )

        # Remove expired subscriptions
        expired_sids = [sid for sid, sub in self._subscriptions.items() if sub.expired]
        for sid in expired_sids:
            del self._subscriptions[sid]

        if not self._subscriptions:
            return

        # Send to all subscribers in parallel with timeout protection.
        # asyncio.gather is cleaner than fire-and-forget tasks and prevents
        # a slow subscriber from blocking notifications for all others.
        async def _notify_one(sub: Subscription) -> None:
            try:
                await asyncio.wait_for(self._send_notify(sub, event_xml), timeout=5.0)
            except asyncio.TimeoutError:
                log.debug(f"Event notify timeout for {sub.sid}")
            except Exception as e:
                log.debug(f"Event notify failed for {sub.sid}: {e}")

        await asyncio.gather(
            *[_notify_one(sub) for sub in self._subscriptions.values()],
            return_exceptions=True,
        )

    async def _send_notify(self, sub: Subscription, event_xml: str) -> None:
        """Send NOTIFY to subscriber (using persistent session)."""
        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "NT": "upnp:event",
            "NTS": "upnp:propchange",
            "SID": sub.sid,
            "SEQ": str(sub.seq),
        }
        sub.seq += 1
        try:
            session = self._get_session()
            async with session.request(
                "NOTIFY",
                sub.callback_url,
                headers=headers,
                data=event_xml,
            ):
                pass
        except Exception as e:
            # Don't remove subscription on failure, just log
            log.debug(f"Event notification failed for {sub.sid}: {e}")

    async def close(self) -> None:
        """Close all sessions."""
        if self._session and not self._session.closed:
            await self._session.close()
        self._subscriptions.clear()


def build_last_change_event(transport_state: str = "", volume: int = -1) -> str:
    """Build LastChange event XML (following MaCast: escape inner Event XML)."""
    event_parts = []
    if transport_state:
        event_parts.append(
            f'<TransportState val="{transport_state}"/>'
        )
    if volume >= 0:
        event_parts.append(f'<Volume channel="Master" val="{volume}"/>')

    inner = "".join(event_parts)
    event_xml = (
        '<Event xmlns="urn:schemas-upnp-org:metadata-1-0/AVT/">'
        f'<InstanceID val="0">{inner}</InstanceID>'
        '</Event>'
    )
    escaped_event = escape(event_xml)

    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">\n'
        "  <e:property>\n"
        f"    <LastChange>{escaped_event}</LastChange>\n"
        "  </e:property>\n"
        "</e:propertyset>"
    )
