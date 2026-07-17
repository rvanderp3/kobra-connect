"""Routes incoming OE cloud HTTP requests to handlers.

The cloud sends WebStreamMsg requests with paths like:
    api/printer/status          (dashboard polling)
    api/printer/snapshot        (webcam snapshot)
    octoeverywhere-command-api/ping
    octoeverywhere-command-api/status
    ...

This module parses the path and dispatches to the appropriate handler,
returning a JSON response body and HTTP status code.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Type alias: handler receives the parsed request body (if any) and returns
# (status_code, response_body_bytes, content_type).
Handler = Callable[[Optional[bytes]], Tuple[int, bytes, str]]


def _json_response(obj: object, status: int = 200) -> Tuple[int, bytes, str]:
    body = json.dumps(obj).encode()
    return (status, body, "application/json")


def _not_found() -> Tuple[int, bytes, str]:
    return _json_response({"Error": "Not found"}, 404)


class CommandRouter:
    """Routes OE command API requests to handler functions."""

    def __init__(self) -> None:
        self._handlers: Dict[str, Handler] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register("ping", self._handle_ping)
        self.register("status", self._handle_status)
        self.register("api/printer/status", self._handle_status)
        self.register("api/printer/snapshot", self._handle_snapshot)
        self.register("api/printer", self._handle_status)
        self.register("api/job", self._handle_job)
        self.register("webcam", self._handle_snapshot)
        self.register("api/live/status", self._handle_status)

    def register(self, path: str, handler: Handler) -> None:
        """Register a handler for a path (matched after normalization)."""
        self._handlers[path.strip("/").lower()] = handler

    def set_status_handler(self, handler: Handler) -> None:
        """Replace the status handler (used to inject the Kobra state translator)."""
        self._handlers["status"] = handler
        self._handlers["api/printer/status"] = handler

    def route(self, raw_path: str, body: Optional[bytes] = None) -> Tuple[int, bytes, str]:
        """Route a request by path. Returns (status_code, body, content_type)."""
        # Normalize: strip leading/trailing /, lowercase, strip query string
        path = raw_path.strip("/").split("?", 1)[0].strip("/").lower()

        # Strip the OE command API prefix if present
        prefix = "octoeverywhere-command-api/"
        if path.startswith(prefix):
            path = path[len(prefix):]

        handler = self._handlers.get(path)
        if handler is None:
            logger.info("No handler for path: %s (raw: %s)", path, raw_path)
            return _not_found()

        try:
            return handler(body)
        except Exception:
            logger.exception("Handler error for %s", path)
            return _json_response({"Error": "Internal error"}, 500)

    # -- built-in handlers ---------------------------------------------------

    @staticmethod
    def _handle_ping(_body: Optional[bytes]) -> Tuple[int, bytes, str]:
        return _json_response({"Message": "Pong"})

    @staticmethod
    def _handle_status(_body: Optional[bytes]) -> Tuple[int, bytes, str]:
        # Default status — overridden by set_status_handler()
        return _json_response({
            "Status": 200,
            "Result": {
                "JobStatus": {
                    "State": "idle",
                    "SubState": None,
                    "Error": None,
                    "Lights": None,
                    "CurrentPrint": None,
                },
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
        })

    @staticmethod
    def _handle_snapshot(_body: Optional[bytes]) -> Tuple[int, bytes, str]:
        from .status_pusher import _PLACEHOLDER_IMAGE
        return (200, _PLACEHOLDER_IMAGE, "image/jpeg")

    @staticmethod
    def _handle_job(_body: Optional[bytes]) -> Tuple[int, bytes, str]:
        return _json_response({
            "Status": 200,
            "Result": {
                "Job": {
                    "Status": "Operational",
                    "State": "Operational",
                    "File": {
                        "Name": "",
                        "Date": 0,
                        "Origin": "",
                        "User": "",
                        "Size": 0,
                    },
                    "Progress": {
                        "Completion": 0.0,
                        "PrintTime": 0,
                        "PrintTimeLeft": 0,
                        "FilePos": 0,
                    },
                    "CurrentPrint": None,
                },
            },
        })
