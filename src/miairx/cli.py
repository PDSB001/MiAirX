"""CLI entry point for MiAirX"""

import argparse
import asyncio
import logging
import os
import sys

from miairx import __version__
from miairx.config.models import AppConfig
from miairx.config.store import ConfigStore
from miairx.core.lifecycle import lifecycle
from miairx.core.logging import setup_logging

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="MiAirX - Modern DLNA/AirPlay bridge for Xiaomi AI speakers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version=f"MiAirX {__version__}",
    )
    
    parser.add_argument(
        "--config", "-c",
        default="conf",
        help="Configuration directory path (default: conf)",
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    
    parser.add_argument(
        "--account", "-a",
        help="Xiaomi account (overrides config)",
    )
    
    parser.add_argument(
        "--password", "-p",
        help="Xiaomi password (overrides config)",
    )
    
    parser.add_argument(
        "--did", "-d",
        help="Device DID (overrides config)",
    )
    
    parser.add_argument(
        "--hostname",
        help="Hostname/IP to bind to (overrides config)",
    )
    
    parser.add_argument(
        "--dlna-port",
        type=int,
        help="DLNA port (default: 8200)",
    )
    
    parser.add_argument(
        "--web-port",
        type=int,
        help="Web management port (default: 8300)",
    )
    
    return parser.parse_args()


def load_config(args: argparse.Namespace) -> AppConfig:
    """Load configuration from file, env vars, and command line args.

    Priority: CLI args > env vars > config.json > defaults
    """
    # Load from file
    store = ConfigStore(conf_path=args.config)
    config = store.load()

    # Environment variable overrides (useful for Docker)
    if not args.account:
        args.account = os.environ.get("MI_USER", "")
    if not args.password:
        args.password = os.environ.get("MI_PASS", "")
    if not args.did:
        args.did = os.environ.get("MI_DID", "")
    if not args.hostname:
        args.hostname = os.environ.get("MIAIR_HOSTNAME", "")
    if not args.dlna_port:
        port = os.environ.get("MIAIR_DLNA_PORT", "")
        if port:
            args.dlna_port = int(port)
    if not args.web_port:
        port = os.environ.get("MIAIR_WEB_PORT", "")
        if port:
            args.web_port = int(port)

    # Override with command line arguments
    if args.account:
        config.account = args.account
    if args.password:
        config.password = args.password
    if args.did:
        config.mi_did = args.did
    if args.hostname:
        config.hostname = args.hostname
    if args.dlna_port:
        config.dlna_port = args.dlna_port
    if args.web_port:
        config.web_port = args.web_port
    if args.verbose:
        config.verbose = True

    return config


async def async_main() -> None:
    """Async main entry point."""
    args = parse_args()
    
    # Load configuration
    config = load_config(args)
    
    # Setup logging
    setup_logging(verbose=config.verbose, log_file=config.log_file)
    
    log.info(f"Starting MiAirX {__version__}")
    log.info(f"Configuration loaded from {config.conf_path}")
    
    # Setup signal handlers
    lifecycle.setup_signal_handlers()
    
    try:
        # Import here to avoid circular imports
        from miairx.app import Application
        
        # Create and start application
        app = Application(config)
        await app.start()
        
        # Wait for shutdown
        await lifecycle.wait_for_shutdown()
    except KeyboardInterrupt:
        log.info("Received keyboard interrupt")
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        await lifecycle.shutdown(exit_code=1)
    finally:
        await lifecycle.shutdown()


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nShutdown complete.")
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
