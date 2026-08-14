"""Tests for logging configuration."""

import logging
import os

from miairx.core.logging import setup_logging


def test_file_log_keeps_info_when_console_is_not_verbose():
    """The file handler must receive INFO records in normal console mode."""
    root = logging.getLogger()
    old_level = root.level
    old_handlers = root.handlers[:]

    try:
        setup_logging(verbose=False, log_file=os.devnull)

        assert root.isEnabledFor(logging.INFO)
        assert any(
            isinstance(handler, logging.FileHandler)
            and handler.level == logging.DEBUG
            for handler in root.handlers
        )
        assert any(
            type(handler) is logging.StreamHandler
            and handler.level == logging.WARNING
            for handler in root.handlers
        )
    finally:
        for handler in root.handlers[:]:
            handler.close()
            root.removeHandler(handler)
        root.setLevel(old_level)
        for handler in old_handlers:
            root.addHandler(handler)
