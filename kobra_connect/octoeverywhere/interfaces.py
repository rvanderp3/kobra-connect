"""Minimal OctoEverywhere interface definitions.

These ABCs mirror the OE core interfaces so the companion is self-contained.
When integrating into a full OE installation, substitute these with the real
imports from ``octoeverywhere.interfaces``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


# ---------------------------------------------------------------------------
# OE data types used by the interfaces
# ---------------------------------------------------------------------------

@dataclass
class CommandResponse:
    ok: bool = True
    status: str = ""
    message: str = ""
    data: Optional[Dict[str, Any]] = None


@dataclass
class HttpResult:
    ok: bool = True
    contentType: str = "application/json"
    statusCode: int = 200
    data: bytes = b""


@dataclass
class ConnectionInfo:
    uri: str = ""
    apiKey: str = ""


@dataclass
class UploadBody:
    filename: str = ""
    data: bytes = b""


@dataclass
class WebcamSettingItem:
    name: str = ""
    url: str = ""
    snapshotUrl: str = ""
    streamUrl: str = ""


# ---------------------------------------------------------------------------
# Feature flags (bitmask)
# ---------------------------------------------------------------------------

FEATURE_LIGHT_CONTROL = 1 << 0
FEATURE_AXIS_MOVEMENT = 1 << 1
FEATURE_HOMING = 1 << 2
FEATURE_EXTRUSION = 1 << 3
FEATURE_TEMPERATURE_CONTROL = 1 << 4
FEATURE_PRINT_START = 1 << 5


# ---------------------------------------------------------------------------
# Abstract interfaces
# ---------------------------------------------------------------------------

class IPlatformCommandHandler(ABC):
    """Handles all printer-level commands dispatched by the OE cloud."""

    @abstractmethod
    def GetCurrentJobStatus(self) -> Union[int, None, Dict[str, Any]]: ...

    @abstractmethod
    def GetPlatformVersionStr(self) -> str: ...

    @abstractmethod
    def GetSupportedFeatureFlags(self) -> int: ...

    @abstractmethod
    def GetConnectionInfo(self) -> ConnectionInfo: ...

    @abstractmethod
    def ExecutePause(self, smartPause: bool, suppressNotificationBool: bool,
                     disableHotendBool: bool, disableBedBool: bool,
                     zLiftMm: int, retractFilamentMm: int,
                     showSmartPausePopup: bool) -> CommandResponse: ...

    @abstractmethod
    def ExecuteResume(self) -> CommandResponse: ...

    @abstractmethod
    def ExecuteCancel(self) -> CommandResponse: ...

    @abstractmethod
    def ExecuteStart(self, args: Optional[Dict[str, Any]]) -> CommandResponse: ...

    @abstractmethod
    def ExecuteSetLight(self, lightName: str, on: bool) -> CommandResponse: ...

    @abstractmethod
    def ExecuteMoveAxis(self, axis: str, distanceMm: float) -> CommandResponse: ...

    @abstractmethod
    def ExecuteHome(self) -> CommandResponse: ...

    @abstractmethod
    def ExecuteExtrude(self, extruder: int, distanceMm: float) -> CommandResponse: ...

    @abstractmethod
    def ExecuteSetTemp(self, bedC: Optional[float], chamberC: Optional[float],
                       toolC: Optional[float], toolNumber: Optional[int]) -> CommandResponse: ...

    @abstractmethod
    def ExecuteSendCommand(self, transportType: str, request: Dict[str, Any],
                           rawPayload: Dict[str, Any]) -> CommandResponse: ...

    @abstractmethod
    def ExecuteFileList(self, args: Optional[Dict[str, Any]]) -> CommandResponse: ...

    @abstractmethod
    def ExecuteFileUpload(self, args: Optional[Dict[str, Any]],
                          uploadBody: UploadBody) -> CommandResponse: ...

    @abstractmethod
    def ExecuteFileDownload(self, args: Optional[Dict[str, Any]]) -> HttpResult: ...

    @abstractmethod
    def ExecuteGetPluginLogs(self, args: Optional[Dict[str, Any]]) -> HttpResult: ...

    @abstractmethod
    def ExecuteFileDelete(self, args: Optional[Dict[str, Any]]) -> CommandResponse: ...


class IPrinterStateReporter(ABC):
    """Reports printer state to the OE notification system."""

    @abstractmethod
    def GetPrintTimeRemainingEstimateInSeconds(self) -> int: ...

    @abstractmethod
    def GetCurrentZOffsetMm(self) -> int: ...

    @abstractmethod
    def GetCurrentLayerInfo(self) -> Tuple[Optional[int], Optional[int]]: ...

    @abstractmethod
    def ShouldPrintingTimersBeRunning(self) -> bool: ...

    @abstractmethod
    def IsPrintWarmingUp(self) -> bool: ...

    @abstractmethod
    def GetTemps(self) -> Tuple[Optional[float], Optional[float]]: ...


class IHostCommandHandler(ABC):
    """Handles host-level commands (e.g. rekey)."""

    @abstractmethod
    def OnRekeyCommand(self) -> bool: ...


class IPopUpInvoker(ABC):
    """Shows UI popups via the OE cloud."""

    @abstractmethod
    def ShowUiPopup(self, title: str, text: str, msgType: str,
                    actionText: Optional[str], actionLink: Optional[str],
                    showForSec: int, onlyShowIfLoadedViaOeBool: bool) -> None: ...


class IWebcamPlatformHelper(ABC):
    """Provides webcam configuration to the OE cloud."""

    @abstractmethod
    def GetWebcamConfig(self) -> Optional[List[WebcamSettingItem]]: ...

    @abstractmethod
    def ShouldQuickCamStreamKeepRunning(self) -> bool: ...

    @abstractmethod
    def OnQuickCamStreamStart(self, url: str) -> None: ...

    @abstractmethod
    def OnQuickCamStreamStall(self, url: str) -> None: ...


class IStateChangeHandler(ABC):
    """Receives connection state events from the OE cloud."""

    @abstractmethod
    def OnPrimaryConnectionEstablished(self, octoKey: str,
                                       connectedAccounts: List[str]) -> None: ...

    @abstractmethod
    def OnPluginUpdateRequired(self) -> None: ...

    @abstractmethod
    def OnRekeyRequired(self) -> None: ...
