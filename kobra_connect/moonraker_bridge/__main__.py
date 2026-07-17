"""CLI entry point for Kobra Moonraker Bridge."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from .bridge import KobraMoonrakerBridge


def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kobra-moonraker-bridge",
        description="Kobra-to-Moonraker bridge for OctoEverywhere Moonraker companion",
    )
    parser.add_argument("--ip", required=True, help="Kobra 3 printer IP address")
    parser.add_argument("--port", type=int, default=7125, help="Moonraker bridge port (default: 7125)")
    parser.add_argument("--webcam-url", default="http://192.168.0.35", help="Axis camera URL (default: http://192.168.0.35)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args(argv)
    _setup_logging(args.debug)

    logger = logging.getLogger(__name__)
    logger.info("Starting Kobra Moonraker Bridge for printer at %s", args.ip)

    bridge = KobraMoonrakerBridge(args.ip, args.port, args.webcam_url)

    def shutdown(signum: int, _frame) -> None:
        logger.info("Shutdown signal received (%s)", signum)
        bridge.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        bridge.start()
        logger.info("Bridge running on port %d. Press Ctrl+C to stop.", args.port)
        while True:
            time.sleep(1)
    except Exception as e:
        logger.error("Bridge failed: %s", e, exc_info=True)
        return 1
    finally:
        bridge.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())