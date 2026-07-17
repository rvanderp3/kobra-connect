"""Kobra Connect — local LAN API client for Anycubic Kobra 3 / S1 printers."""

from .client import KobraClient
from .handshake import CloudModeError, HandshakeError, do_handshake
from .models import (
    FanSpeed,
    HandshakeResult,
    PauseState,
    PrinterInfo,
    PrintProject,
    Temperature,
)

__all__ = [
    "KobraClient",
    "CloudModeError",
    "HandshakeError",
    "do_handshake",
    "FanSpeed",
    "HandshakeResult",
    "PauseState",
    "PrinterInfo",
    "PrintProject",
    "Temperature",
]

# OctoEverywhere companion is importable but not auto-loaded:
#   from kobra_connect.octoeverywhere.host import KobraHost
