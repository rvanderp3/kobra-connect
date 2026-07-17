"""OE IPlatformCommandHandler implementation for Kobra 3.

MVP: monitoring only.  All control commands return "not supported".
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..client import KobraClient
from .interfaces import (
    CommandResponse,
    ConnectionInfo,
    HttpResult,
    IPlatformCommandHandler,
    UploadBody,
)
from .state_translator import KobraStateTranslator

logger = logging.getLogger(__name__)

_NOT_SUPPORTED = CommandResponse(ok=False, message="Not supported on Kobra 3 (monitoring-only companion)")

__version__ = "0.1.0"


class KobraCommandHandler(IPlatformCommandHandler):

    def __init__(self, client: KobraClient, translator: KobraStateTranslator) -> None:
        self._client = client
        self._translator = translator

    # -- queries -------------------------------------------------------------

    def GetCurrentJobStatus(self) -> Optional[Dict[str, Any]]:
        return self._translator.get_job_status().to_dict()

    def GetPlatformVersionStr(self) -> str:
        return f"kobra-connect {__version__}"

    def GetSupportedFeatureFlags(self) -> int:
        return 0

    def GetConnectionInfo(self) -> ConnectionInfo:
        return ConnectionInfo(uri=f"lan://{self._client.host}")

    # -- control commands (not supported in MVP) -----------------------------

    def ExecutePause(self, *args: Any, **kwargs: Any) -> CommandResponse:
        return _NOT_SUPPORTED

    def ExecuteResume(self) -> CommandResponse:
        return _NOT_SUPPORTED

    def ExecuteCancel(self) -> CommandResponse:
        return _NOT_SUPPORTED

    def ExecuteStart(self, args: Optional[Dict[str, Any]]) -> CommandResponse:
        return _NOT_SUPPORTED

    def ExecuteSetLight(self, lightName: str, on: bool) -> CommandResponse:
        return _NOT_SUPPORTED

    def ExecuteMoveAxis(self, axis: str, distanceMm: float) -> CommandResponse:
        return _NOT_SUPPORTED

    def ExecuteHome(self) -> CommandResponse:
        return _NOT_SUPPORTED

    def ExecuteExtrude(self, extruder: int, distanceMm: float) -> CommandResponse:
        return _NOT_SUPPORTED

    def ExecuteSetTemp(self, bedC: Optional[float], chamberC: Optional[float],
                       toolC: Optional[float], toolNumber: Optional[int]) -> CommandResponse:
        return _NOT_SUPPORTED

    def ExecuteSendCommand(self, transportType: str, request: Dict[str, Any],
                           rawPayload: Dict[str, Any]) -> CommandResponse:
        return _NOT_SUPPORTED

    def ExecuteFileList(self, args: Optional[Dict[str, Any]]) -> CommandResponse:
        return _NOT_SUPPORTED

    def ExecuteFileUpload(self, args: Optional[Dict[str, Any]],
                          uploadBody: UploadBody) -> CommandResponse:
        return _NOT_SUPPORTED

    def ExecuteFileDownload(self, args: Optional[Dict[str, Any]]) -> HttpResult:
        return HttpResult(ok=False, statusCode=501, data=b"Not supported")

    def ExecuteGetPluginLogs(self, args: Optional[Dict[str, Any]]) -> HttpResult:
        return HttpResult(ok=False, statusCode=501, data=b"Not supported")

    def ExecuteFileDelete(self, args: Optional[Dict[str, Any]]) -> CommandResponse:
        return _NOT_SUPPORTED
