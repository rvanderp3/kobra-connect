"""Direct CDN snapshot uploader for OctoEverywhere live view.

The cloud polls the webcam through the tunnel but doesn't always cache
snapshots to the CDN. This module uploads snapshots directly to the CDN
endpoint so the dashboard can display the live view.
"""

from __future__ import annotations

import logging
import threading
import requests
from typing import Optional

from .oe_credentials import OeCredentials

logger = logging.getLogger(__name__)

_CDN_URL = "https://nyc.octoeverywhere.com/cdn-api/live/snapshot"


class CdnUploader:
    """Periodically uploads webcam snapshots to the OE CDN."""

    def __init__(
        self,
        creds: OeCredentials,
        capture_fn,
        interval: float = 5.0,
    ) -> None:
        self._creds = creds
        self._capture_fn = capture_fn
        self._interval = interval
        self._octokey: str = ""
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "OctoEverywhere-OctoPrint/2.1.8 (kobra-connect)",
        })

    def set_octokey(self, octokey: str) -> None:
        self._octokey = octokey

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="oe-cdn-upload")
        self._thread.start()
        logger.info("CDN uploader started (interval=%.0fs)", self._interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._upload()
            except Exception:
                logger.warning("CDN upload error", exc_info=True)

    def _upload(self) -> None:
        octokey = self._octokey or self._creds.octokey
        if not octokey:
            return

        snapshot = self._capture_fn()
        if not snapshot:
            return

        resp = self._session.post(
            _CDN_URL,
            headers={
                "OctoKey": octokey,
                "PrinterId": self._creds.printer_id,
            },
            files={"snapshot": ("snapshot.jpg", snapshot, "image/jpeg")},
            timeout=10,
        )
        if resp.ok:
            logger.debug("CDN upload OK (%d bytes, status=%d)", len(snapshot), resp.status_code)
        else:
            logger.warning(
                "CDN upload failed: %d %s",
                resp.status_code,
                resp.text[:200],
            )
