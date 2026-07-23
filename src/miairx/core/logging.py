"""Structured logging setup for MiAirX"""

import logging
import sys
from pathlib import Path

import structlog


def setup_logging(verbose: bool = False, log_file: str | None = None) -> None:
    """Configure structured logging for MiAirX.

    Log levels (default mode, verbose=False):
      Console: WARNING and above only (clean output)
      File:    DEBUG and above (full trace if configured)
    Verbose mode (-v):
      Console: DEBUG and above
      File:    DEBUG and above

    Args:
        verbose: Enable debug logging on console
        log_file: Optional log file path (always DEBUG level)
    """
    console_level = logging.DEBUG if verbose else logging.WARNING

    # Configure structlog
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if verbose else structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(console_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard logging
    root_logger = logging.getLogger()
    root_logger.setLevel(console_level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console handler — only WARNING+ by default, DEBUG in verbose mode
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler — always DEBUG (full trace preservation)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
