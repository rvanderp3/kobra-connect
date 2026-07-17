"""Periodically pushes printer status to the OE cloud.

The dashboard quick view reads from the cloud's cached status, which is
populated by HTTP POSTs from the companion to the OE notifications endpoint.
"""

from __future__ import annotations

import logging
import random
import string
import threading
import time
from typing import Optional

import requests

from .oe_credentials import OeCredentials
from .state_translator import KobraStateTranslator
from .webcam_provider import capture_snapshot

logger = logging.getLogger(__name__)

_NOTIFICATIONS_URL = (
    "https://printer-events-v1-oeapi.octoeverywhere.com"
    "/api/printernotifications/printerevent"
)

_PRINT_ID_CHARS = string.ascii_letters + string.digits

import struct
import subprocess
import tempfile
import os
import zlib

# 320x240 dark gray JPEG — placeholder snapshot for the OE cloud.
def _make_placeholder_jpeg(width=320, height=240) -> bytes:
    """Create a placeholder JPEG using macOS sips."""
    # Build a valid PNG, then convert to JPEG via sips
    def _png_chunk(typ: bytes, data: bytes) -> bytes:
        c = typ + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    raw = b''
    for y in range(height):
        raw += b'\x00'
        for x in range(width):
            raw += b'\x3a\x3a\x3a'
    png = (b'\x89PNG\r\n\x1a\n' +
           _png_chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
           _png_chunk(b'IDAT', zlib.compress(raw)) +
           _png_chunk(b'IEND', b''))

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        f.write(png)
        png_path = f.name
    jpg_path = png_path.replace('.png', '.jpg')
    try:
        subprocess.run(['sips', '-s', 'format', 'jpeg', png_path, '--out', jpg_path],
                       capture_output=True, timeout=30)
        with open(jpg_path, 'rb') as f:
            return f.read()
    except Exception:
        return png  # fallback: return PNG (better than nothing)
    finally:
        try:
            os.unlink(png_path)
            os.unlink(jpg_path)
        except Exception:
            pass

_PLACEHOLDER_IMAGE = _make_placeholder_jpeg()


def _generate_print_id() -> str:
    return "".join(random.choices(_PRINT_ID_CHARS, k=60))


class StatusPusher:
    """Pushes printer status to the OE cloud at regular intervals.

    The cloud caches the latest push and serves it to the dashboard quick view.
    """

    _PRINTING_STATES = frozenset(["printing", "paused", "warmingup"])

    def __init__(
        self,
        credentials: OeCredentials,
        translator: KobraStateTranslator,
        interval_sec: float = 10.0,
    ) -> None:
        self._creds = credentials
        self._translator = translator
        self._interval = interval_sec
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._current_print_id: str = ""
        self._last_state: str = ""
        self._octokey: str = ""
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "OctoEverywhere-OctoPrint/2.1.8 (kobra-connect)",
        })

    def set_octokey(self, octokey: str) -> None:
        """Set the octokey received from the OE cloud handshake."""
        self._octokey = octokey
        logger.info("OctoKey set from handshake: %s...", octokey[:12] if octokey else "none")

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="oe-status-pusher")
        self._thread.start()
        logger.info("Status pusher started (interval=%.0fs)", self._interval)
        # Push immediately on start
        threading.Thread(target=self._push, daemon=True, name="oe-status-push-init").start()
        # Send test event to mark printer online (matching real plugin behavior)
        threading.Thread(target=self._push_test_event, daemon=True, name="oe-status-push-test").start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _push_test_event(self) -> None:
        """Send a 'test' event to mark the printer as online (matches real plugin startup)."""
        octokey = self._octokey or self._creds.octokey
        data = {
            "PrinterId": self._creds.printer_id,
            "OctoKey": octokey,
            "Event": "test",
            "TimeRemainingSec": "-1",
            "CurrentLayer": "0",
            "TotalLayers": "0",
            "ProgressPercentage": "0",
            "DurationSec": "0",
            "PluginVersion": "kobra-connect-0.1.0",
        }
        logger.info("Pushing test event (printer online signal)")
        snapshot = capture_snapshot() or _PLACEHOLDER_IMAGE
        try:
            resp = self._session.post(
                _NOTIFICATIONS_URL,
                data=data,
                files={"snapshot": ("snapshot.jpg", snapshot, "image/jpeg")},
                timeout=10,
            )
            logger.info("Test event push: status_code=%d body=%s", resp.status_code, resp.text)
        except requests.RequestException as e:
            logger.warning("Test event push failed: %s", e)

    def _run(self) -> None:
        logger.info("Status pusher thread running")
        while not self._stop.is_set():
            try:
                self._push()
            except Exception:
                logger.exception("Status push failed unexpectedly")
            self._stop.wait(self._interval)

    def _push(self) -> None:
        info = self._translator.get_info()
        job_status = self._translator.get_job_status()

        state = job_status.State
        prev = self._last_state

        # Determine event based on state transition
        event, is_transition = self._resolve_event(prev, state)

        # Manage print ID lifecycle.
        # IMPORTANT: capture the PrintId BEFORE clearing it so end-of-print
        # events (done/error/failed) include the completed print's ID.
        print_id = self._current_print_id
        if event == "started":
            print_id = _generate_print_id()
            self._current_print_id = print_id
        elif event in ("done", "error", "failed"):
            self._current_print_id = ""
        self._last_state = state

        # Only push when there's an active print or a relevant transition.
        # The real OE plugin never sends idle heartbeats — the WebSocket
        # tunnel keeps the connection alive. Sending idle timerprogress
        # with random PrintIds confuses the cloud.
        if state not in self._PRINTING_STATES and not is_transition:
            return

        progress = 0.0
        duration = 0
        time_remaining = -1
        filename = ""
        current_layer = 0
        total_layers = 0

        if info is not None and info.project is not None:
            p = info.project
            progress = float(p.progress)
            duration = p.print_time
            time_remaining = p.remain_time if p.remain_time > 0 else -1
            filename = p.filename
            current_layer = p.curr_layer or 0
            total_layers = p.total_layers or 0

        octokey = self._octokey or self._creds.octokey
        logger.info("Using OctoKey from: handshake=%s length=%d", bool(self._octokey), len(octokey))
        logger.info("PrinterId: %s... (length=%d)", self._creds.printer_id[:12], len(self._creds.printer_id))

        data = {
            "PrinterId": self._creds.printer_id,
            "OctoKey": octokey,
            "Event": event,
            "FileName": filename,
            "FileSizeKb": "0",
            "FilamentUsageMm": "0",
            "FilamentWeightMg": "0",
            "TimeRemainingSec": str(time_remaining),
            "CurrentLayer": str(current_layer),
            "TotalLayers": str(total_layers),
            "ProgressPercentage": str(int(progress)),
            "DurationSec": str(duration),
            "PluginVersion": "kobra-connect-0.1.0",
        }

        # Only include PrintId when there's an active print
        if print_id:
            data["PrintId"] = print_id

        if event == "started":
            data["ProgressPercentage"] = "0"
            data["DurationSec"] = "0"
            data["TimeRemainingSec"] = "-1"

        if event == "timerprogress":
            hours_count = duration // 3600 if duration > 0 else 0
            data["HoursCount"] = str(hours_count)

        if event == "progress":
            snapped = (int(progress) // 10) * 10
            data["ProgressPercentage"] = str(snapped)

        logger.info("Pushing status: state=%s->%s event=%s progress=%.0f%% transition=%s",
                     prev, state, event, progress, is_transition)
        logger.info("Push payload: %s", data)

        snapshot = capture_snapshot() or _PLACEHOLDER_IMAGE
        try:
            resp = self._session.post(
                _NOTIFICATIONS_URL,
                data=data,
                files={"snapshot": ("snapshot.jpg", snapshot, "image/jpeg")},
                timeout=10,
            )
            logger.info("Status push response: status_code=%d body=%s", resp.status_code, resp.text)
            if resp.status_code != 200:
                logger.warning("Status push returned %d: %s", resp.status_code, resp.text[:200])
            else:
                logger.info("Status push OK (event=%s, progress=%.0f%%) response=%s",
                             event, progress, resp.text[:200])
        except requests.RequestException as e:
            logger.warning("Status push request failed: %s", e)

    @staticmethod
    def _resolve_event(prev: str, state: str) -> tuple[str, bool]:
        """Resolve the OE event name and whether this is a state transition.

        Returns (event_name, is_transition).
        """
        printing = StatusPusher._PRINTING_STATES

        # First push — treat as transition
        if not prev:
            if state in printing:
                return "started", True
            return "timerprogress", True

        # No change — steady state
        if state == prev:
            if state == "printing":
                return "progress", False
            if state == "paused":
                return "paused", False
            return "timerprogress", False

        # State transitions
        # idle started a print
        if prev in ("idle", "complete", "cancelled", "error", "") and state in printing:
            return "started", True
        # print resumed
        if prev == "paused" and state == "printing":
            return "resume", True
        # print paused
        if prev in printing and state == "paused":
            return "paused", True
        # print completed
        if prev in printing and state == "complete":
            return "done", True
        # print failed
        if prev in printing and state == "error":
            return "error", True
        # print cancelled
        if prev in printing and state == "cancelled":
            return "failed", True
        # print stopped (direct to idle)
        if prev in printing and state == "idle":
            return "done", True

        return "timerprogress", True
