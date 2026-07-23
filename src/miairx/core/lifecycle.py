"""Graceful shutdown and lifecycle management for MiAirX"""

import asyncio
import logging
import signal
import sys
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


class LifecycleManager:
    """Manages application lifecycle with graceful shutdown."""

    def __init__(self) -> None:
        self._shutdown_callbacks: list[Callable[[], Any]] = []
        self._is_shutting_down = False
        self._shutdown_event = asyncio.Event()

    def register_shutdown_callback(self, callback: Callable[[], Any]) -> None:
        """Register a callback to be called during shutdown."""
        self._shutdown_callbacks.append(callback)

    async def shutdown(self, exit_code: int = 0) -> None:
        """Perform graceful shutdown."""
        if self._is_shutting_down:
            return

        self._is_shutting_down = True
        log.info("Starting graceful shutdown...")

        # Call all registered shutdown callbacks
        for callback in self._shutdown_callbacks:
            try:
                result = callback()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                log.error(f"Error in shutdown callback: {e}")

        log.info("Shutdown complete")
        self._shutdown_event.set()

        if exit_code != 0:
            sys.exit(exit_code)

    async def wait_for_shutdown(self) -> None:
        """Wait until shutdown is triggered."""
        await self._shutdown_event.wait()

    def trigger_shutdown(self) -> None:
        """Trigger shutdown from synchronous code."""
        if not self._is_shutting_down:
            asyncio.create_task(self.shutdown())

    def setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        if sys.platform == "win32":
            # Windows doesn't support SIGINT/SIGTERM in the same way
            # Try to use win32api if available, otherwise rely on KeyboardInterrupt
            try:
                import win32api

                def handler(ctrl_type: int) -> bool:
                    if ctrl_type in (0, 2):  # CTRL_C_EVENT, CTRL_BREAK_EVENT
                        self.trigger_shutdown()
                        return True
                    return False

                win32api.SetConsoleCtrlHandler(handler, True)
            except ImportError:
                log.warning("win32api not available, using KeyboardInterrupt for shutdown")
        else:
            # Unix-like systems
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self.trigger_shutdown)


# Global lifecycle manager instance
lifecycle = LifecycleManager()
