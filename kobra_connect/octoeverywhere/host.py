"""OctoEverywhere companion host for Kobra 3.

Wires together the Kobra client, state translator, command handler, and
state reporter.  Provides both a standalone monitoring loop and the
integration points needed by the full OctoEverywhere plugin.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import List, Optional

from ..client import KobraClient
from .command_handler import KobraCommandHandler
from .interfaces import (
    IHostCommandHandler,
    IPopUpInvoker,
    IStateChangeHandler,
)
from .state_reporter import KobraStateReporter
from .state_translator import KobraStateTranslator

logger = logging.getLogger(__name__)


class KobraHost(IHostCommandHandler, IPopUpInvoker, IStateChangeHandler):
    """Main host class for the Kobra 3 OE companion.

    Usage::

        host = KobraHost("192.168.0.71")
        host.run_standalone()        # prints status to stdout

    For full OE integration, use the component accessors::

        host = KobraHost("192.168.0.71")
        host.connect()               # handshake + MQTT connect
        handler = host.command_handler
        reporter = host.state_reporter
    """

    def __init__(self, ip: str, connect_timeout: float = 10.0) -> None:
        self._ip = ip
        self._connect_timeout = connect_timeout
        self._client: Optional[KobraClient] = None
        self._translator: Optional[KobraStateTranslator] = None
        self._command_handler: Optional[KobraCommandHandler] = None
        self._state_reporter: Optional[KobraStateReporter] = None

    # -- component accessors -------------------------------------------------

    @property
    def client(self) -> KobraClient:
        assert self._client is not None, "call connect() first"
        return self._client

    @property
    def translator(self) -> KobraStateTranslator:
        assert self._translator is not None, "call connect() first"
        return self._translator

    @property
    def command_handler(self) -> KobraCommandHandler:
        assert self._command_handler is not None, "call connect() first"
        return self._command_handler

    @property
    def state_reporter(self) -> KobraStateReporter:
        assert self._state_reporter is not None, "call connect() first"
        return self._state_reporter

    # -- lifecycle -----------------------------------------------------------

    def connect(self) -> None:
        """Handshake + MQTT connect to the Kobra printer."""
        logger.info("Connecting to Kobra 3 at %s ...", self._ip)
        self._client = KobraClient(self._ip)
        self._client.connect(timeout=self._connect_timeout)
        logger.info("Connected. Subscribing to report topics ...")

        self._translator = KobraStateTranslator(self._client)
        self._command_handler = KobraCommandHandler(self._client, self._translator)
        self._state_reporter = KobraStateReporter(self._translator)
        logger.info("Companion ready.")

    def disconnect(self) -> None:
        if self._client:
            self._client.disconnect()
            self._client = None

    # -- standalone monitoring -----------------------------------------------

    def run_standalone(self, poll_interval: float = 2.0) -> None:
        """Connect and print status to stdout until interrupted.

        Useful for testing without the full OE cloud infrastructure.
        """
        self.connect()
        print(f"Monitoring Kobra 3 at {self._ip} (Ctrl+C to stop)\n")

        try:
            while True:
                status = self._translator.get_job_status()
                info = self._translator.get_info()
                temp = self._translator.get_temperature()

                if info is not None:
                    self._print_status(info, temp, status)
                else:
                    print("  Waiting for first report ...")

                time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("\nStopping ...")
        finally:
            self.disconnect()

    @staticmethod
    def _print_status(info, temp, status) -> None:
        project = info.project
        state_str = status.State.upper()

        lines = [
            f"  Printer: {info.name} ({info.model}) — {info.firmware}",
            f"  State:   {state_str}",
        ]

        if temp is not None:
            lines.append(
                f"  Temps:   nozzle {temp.curr_nozzle:.1f}/{temp.target_nozzle:.1f}°C  "
                f"bed {temp.curr_bed:.1f}/{temp.target_bed:.1f}°C"
            )

        if project is not None and project.state == "printing":
            lines.append(
                f"  Print:   {project.filename} — {project.progress}% "
                f"(layer {project.curr_layer}/{project.total_layers})"
            )
            mins = project.remain_time // 60
            lines.append(f"  Time:    {mins} min remaining")

        lines.append("")
        print("\n".join(lines))

    # -- OE integration accessors --------------------------------------------

    def get_all_components(self):
        """Return all components as a dict for OE plugin integration.

        Returns a dict with keys: ``command_handler``, ``state_reporter``,
        ``translator``, ``client``.
        """
        return {
            "command_handler": self.command_handler,
            "state_reporter": self.state_reporter,
            "translator": self.translator,
            "client": self.client,
        }

    # -- IHostCommandHandler -------------------------------------------------

    def OnRekeyCommand(self) -> bool:
        return False

    # -- IPopUpInvoker -------------------------------------------------------

    def ShowUiPopup(self, title: str, text: str, msgType: str,
                    actionText: Optional[str], actionLink: Optional[str],
                    showForSec: int, onlyShowIfLoadedViaOeBool: bool) -> None:
        logger.info("Popup: [%s] %s — %s", msgType, title, text)

    # -- IStateChangeHandler -------------------------------------------------

    def OnPrimaryConnectionEstablished(self, octoKey: str,
                                       connectedAccounts: List[str]) -> None:
        logger.info("OE cloud connected (accounts: %s)", connectedAccounts)

    def OnPluginUpdateRequired(self) -> None:
        logger.warning("OE plugin update required")

    def OnRekeyRequired(self) -> None:
        logger.warning("OE rekey required")
