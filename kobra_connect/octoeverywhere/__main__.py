"""CLI entry point for the Kobra 3 OctoEverywhere companion.

Usage::

    # Standalone monitoring (no OE cloud)
    kobra-oe monitor --ip 192.168.0.71

    # Connect to OctoEverywhere cloud
    kobra-oe run --ip 192.168.0.71

    # Legacy shorthand (same as monitor)
    kobra-oe --ip 192.168.0.71
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def cmd_monitor(args: argparse.Namespace) -> None:
    """Standalone monitoring — print status to stdout."""
    from .host import KobraHost

    host = KobraHost(args.ip, connect_timeout=args.timeout)
    host.run_standalone(poll_interval=args.poll)


def cmd_run(args: argparse.Namespace) -> None:
    """Full OE cloud companion — connect printer to OctoEverywhere."""
    from .command_router import CommandRouter
    from .host import KobraHost
    from .oe_client import OeClient
    from .oe_credentials import load_or_create

    # 1. Load or generate OE credentials
    data_dir = args.data_dir
    creds = load_or_create(data_dir)
    logger.info("Printer ID: %s", creds.printer_id)

    # 2. Connect to Kobra printer
    host = KobraHost(args.ip, connect_timeout=args.timeout)
    host.connect()
    logger.info("Connected to Kobra 3 at %s", args.ip)

    # 3. Set up command router with Kobra status handler
    translator = host.translator
    router = CommandRouter()

    def handle_status(_body: Optional[bytes]):
        import json
        status = translator.get_job_status()
        body = json.dumps({
            "Status": 200,
            "Result": {
                "JobStatus": status.to_dict(),
                "OctoEverywhereStatus": {
                    "MostRecentPrintIdStr": "",
                    "PrintStartTimeSec": 0,
                    "Gadget": {
                        "LastScore": 0.0,
                        "ScoreHistory": [],
                        "TimeSinceLastScoreSec": 0.0,
                        "IntervalSec": 0.0,
                        "IsSuppressed": False,
                        "TimeSinceLastWarnSec": None,
                        "TimeSinceLastPauseSec": None,
                    },
                },
                "PlatformVersion": "kobra-connect-0.1.0",
                "Features": 32,
                "ListWebcams": {
                    "DefaultIndex": 0,
                    "Webcams": [
                        {
                            "Name": "Default",
                            "FlipH": False,
                            "FlipV": False,
                            "Rotation": 0,
                            "Enabled": True,
                        }
                    ],
                },
            },
        }).encode()
        return (200, body, "application/json")

    router.set_status_handler(handle_status)

    # OctoPrint-compatible API handlers (dashboard proxies these through WebStreamMsg)
    def handle_api_job(_body: Optional[bytes]):
        import json
        info = translator.get_info()
        if info is None or info.project is None:
            resp = {
                "state": "Operational",
                "job": {
                    "file": {"name": "", "origin": "", "size": 0, "date": 0},
                    "estimatedPrintTime": 0,
                },
                "progress": {
                    "completion": None,
                    "filepos": 0,
                    "printTime": 0,
                    "printTimeLeft": 0,
                },
            }
        else:
            p = info.project
            is_printing = p.state == "printing"
            is_paused = p.pause.value in (2, 3) if p.pause else False
            state = "Printing" if is_printing and not is_paused else ("Paused" if is_paused else "Operational")
            resp = {
                "state": state,
                "job": {
                    "file": {"name": p.filename, "origin": "local", "size": 0, "date": 0},
                    "estimatedPrintTime": p.print_time + p.remain_time if p.remain_time else p.print_time,
                },
                "progress": {
                    "completion": p.progress,
                    "filepos": 0,
                    "printTime": p.print_time,
                    "printTimeLeft": p.remain_time,
                },
            }
        body = json.dumps(resp).encode()
        return (200, body, "application/json")

    def handle_api_printer(_body: Optional[bytes]):
        import json
        temp = translator.get_temperature()
        info = translator.get_info()
        if temp is None:
            return (200, json.dumps({"state": {"text": "Operational", "flags": {"operational": True, "ready": True}}}).encode(), "application/json")
        bed = {"actual": temp.curr_bed, "target": temp.target_bed, "offset": 0}
        tool0 = {"actual": temp.curr_nozzle, "target": temp.target_nozzle, "offset": 0}
        resp = {
            "state": {"text": "Operational", "flags": {"operational": True, "ready": True}},
            "temperature": {"bed": bed, "tool0": tool0},
        }
        return (200, json.dumps(resp).encode(), "application/json")

    def handle_root(_body: Optional[bytes]):
        import json
        return (200, json.dumps({"api": "0.1", "server": "kobra-connect", "text": "Kobra 3 Companion"}).encode(), "application/json")

    from .webcam_provider import capture_snapshot

    def handle_webcam(_body: Optional[bytes]):
        return (200, capture_snapshot(), "image/jpeg")

    router.register("api/job", handle_api_job)
    router.register("api/printer", handle_api_printer)
    router.register("webcam", handle_webcam)
    router.register("", handle_root)

    # 4. Connect to OE cloud
    oe_client = OeClient(
        credentials=creds,
        router=router,
        local_ip=args.ip,
        data_dir=data_dir,
    )

    # Start OE client in background, wait for handshake
    import threading
    oe_thread = threading.Thread(target=oe_client.run, daemon=True, name="oe-client")
    oe_thread.start()

    logger.info("Waiting for OE cloud handshake ...")
    oe_client._connected.wait(timeout=30)
    if not oe_client._connected.is_set():
        logger.warning("OE handshake timed out — status pusher will retry")

    # 5. Start periodic status pusher (populates cloud cache for quick view)
    from .status_pusher import StatusPusher
    pusher = StatusPusher(creds, translator, interval_sec=10.0)
    pusher.set_octokey(oe_client.octokey)
    pusher.start()

    # 5.5 Start CDN uploader for live view snapshots
    from .cdn_uploader import CdnUploader
    cdn_uploader = CdnUploader(creds, capture_snapshot, interval=5.0)
    cdn_uploader.set_octokey(oe_client.octokey)
    cdn_uploader.start()

    # 6. Handle shutdown
    def shutdown(signum: int, _frame) -> None:
        logger.info("Shutting down ...")
        cdn_uploader.stop()
        pusher.stop()
        oe_client.stop()
        host.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 7. Print link URL on first run, then run
    if not args.skip_link:
        link_url = f"https://octoeverywhere.com/getstarted?printerid={creds.printer_id}"
        print(f"\n  Link your printer to OctoEverywhere:\n\n  {link_url}\n")

    logger.info("Starting OE cloud companion (Ctrl+C to stop) ...")
    try:
        while oe_thread.is_alive():
            oe_thread.join(timeout=1.0)
    except KeyboardInterrupt:
        pass
    finally:
        cdn_uploader.stop()
        pusher.stop()
        oe_client.stop()
        host.disconnect()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="kobra-oe",
        description="OctoEverywhere companion for Anycubic Kobra 3 printers",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    sub = parser.add_subparsers(dest="command")

    # -- monitor subcommand (default) --
    mon = sub.add_parser("monitor", help="Standalone monitoring (no OE cloud)")
    mon.add_argument("--ip", required=True, help="Kobra 3 printer IP")
    mon.add_argument("--timeout", type=float, default=10.0, help="MQTT connect timeout (s)")
    mon.add_argument("--poll", type=float, default=2.0, help="Status poll interval (s)")

    # -- run subcommand --
    run = sub.add_parser("run", help="Connect to OctoEverywhere cloud")
    run.add_argument("--ip", required=True, help="Kobra 3 printer IP")
    run.add_argument("--timeout", type=float, default=10.0, help="MQTT connect timeout (s)")
    run.add_argument("--data-dir", default=".", help="Directory for OE secrets file")
    run.add_argument("--skip-link", action="store_true", help="Don't print link URL")

    # -- legacy: bare --ip defaults to monitor --
    parser.add_argument("--ip", help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=10.0, help=argparse.SUPPRESS)
    parser.add_argument("--poll", type=float, default=2.0, help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    _setup_logging(args.debug)

    if args.command == "run":
        cmd_run(args)
    elif args.command == "monitor":
        cmd_monitor(args)
    elif args.ip:
        # Legacy: --ip without subcommand → monitor
        cmd_monitor(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
