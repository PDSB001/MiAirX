"""In-memory ring buffer for real-time log streaming.

A ``MemoryLogHandler`` feeds formatted log records into a shared ring buffer.
The web layer drains this buffer over Server-Sent Events so the management
console can show a live log tail without tailing a file. The buffer is bounded
(``maxlen``) so it cannot grow unboundedly over long-running sessions.

Note on thread-safety: MiAirX is a single-threaded asyncio application, so log
records are emitted on the event loop thread. The buffer still uses a lock to
guard the deque so a stray emit from a background thread (e.g. a library
callback) cannot corrupt the snapshot.
"""

import logging
import threading
from collections import deque
from datetime import datetime


class LogBuffer:
    """Bounded store of the most recent formatted log records."""

    def __init__(self, maxlen: int = 1000):
        self._records: deque[dict] = deque(maxlen=maxlen)
        self._subscribers: set = set()
        self._lock = threading.Lock()

    def append(self, record: dict) -> None:
        with self._lock:
            self._records.append(record)
            subscribers = list(self._subscribers)
        for queue in subscribers:
            try:
                queue.put_nowait(record)
            except Exception:  # noqa: BLE001 - full/closed queue is non-fatal
                pass

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._records)

    def subscribe(self, queue) -> None:
        with self._lock:
            self._subscribers.add(queue)

    def unsubscribe(self, queue) -> None:
        with self._lock:
            self._subscribers.discard(queue)


class MemoryLogHandler(logging.Handler):
    """Logging handler that formats records and appends them to a LogBuffer."""

    def __init__(self, buffer: LogBuffer):
        super().__init__(level=logging.DEBUG)
        self._buffer = buffer
        self.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "time": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
                "level": record.levelname,
                "name": record.name,
                "message": self.format(record),
            }
        except Exception:  # noqa: BLE001 - never let logging raise
            return
        self._buffer.append(entry)


# Process-wide shared buffer. setup_logging installs a handler that feeds it,
# and the web layer drains it for SSE streaming.
_LOG_BUFFER = LogBuffer(maxlen=1000)


def get_log_buffer() -> LogBuffer:
    """Return the process-wide log buffer."""
    return _LOG_BUFFER
