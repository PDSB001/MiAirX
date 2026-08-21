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

    parser.add_argument(
        "--airplay-port-start",
        type=int,
        help="First AirPlay TCP port (two consecutive ports per speaker; default: 7000)",
    )
    
    return parser.parse_args()


def load_config(args: argparse.Namespace) -> AppConfig:
    """Load configuration from file, env vars, and command line args.

    Priority: CLI args > env vars > config.json > defaults
    """
    # Load from file
    store = ConfigStore(conf_path=args.config)
    config = store.load()

    # Collect all overrides and validate the resulting configuration once.
    # This keeps CLI and Docker environment values under the same Pydantic
    # range and cross-field constraints as config.json and the Web API.
    overrides = {
        "account": args.account or os.environ.get("MI_USER", ""),
        "password": args.password or os.environ.get("MI_PASS", ""),
        "mi_did": args.did or os.environ.get("MI_DID", ""),
        "hostname": args.hostname or os.environ.get("MIAIR_HOSTNAME", ""),
        "dlna_port": args.dlna_port or os.environ.get("MIAIR_DLNA_PORT", ""),
        "web_port": args.web_port or os.environ.get("MIAIR_WEB_PORT", ""),
        "airplay_port_start": (
            args.airplay_port_start or os.environ.get("MIAIR_AIRPLAY_PORT_START", "")
        ),
        "web_password": os.environ.get("MIAIR_WEB_PASSWORD", ""),
    }
    merged = config.model_dump()
    merged.update({key: value for key, value in overrides.items() if value != ""})
    if args.verbose:
        merged["verbose"] = True
    return AppConfig.model_validate(merged)


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
