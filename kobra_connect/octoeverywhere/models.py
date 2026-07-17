"""OE-compatible data models that map Kobra state to the cloud format."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..models import PrinterInfo, PauseState, Temperature


# OE job states
STATE_IDLE = "idle"
STATE_PRINTING = "printing"
STATE_PAUSED = "paused"
STATE_COMPLETE = "complete"
STATE_CANCELLED = "cancelled"
STATE_ERROR = "error"
STATE_WARMINGUP = "warmingup"

OE_INT_MAX = 2147483600


def _map_state(info: PrinterInfo) -> str:
    """Map Kobra printer state to OE job state string."""
    project = info.project
    if project is None:
        return STATE_IDLE

    if project.state == "printing":
        if project.pause == PauseState.PAUSED:
            return STATE_PAUSED
        if project.pause == PauseState.PAUSING:
            return STATE_PAUSED
        if project.pause == PauseState.STOPPING:
            return STATE_CANCELLED
        return STATE_PRINTING

    if project.state in ("preparing", "heating", "leveling"):
        return STATE_WARMINGUP

    if project.state == "finish":
        return STATE_COMPLETE

    if project.state == "idle":
        return STATE_IDLE

    if project.state == "error":
        return STATE_ERROR

    if project.state == "cancelled":
        return STATE_CANCELLED

    return STATE_IDLE


def _map_sub_state(info: PrinterInfo) -> Optional[str]:
    """Map Kobra state to a human-readable sub-state string."""
    project = info.project
    if project is None:
        return None

    if info.temperature.target_nozzle > 0 and info.temperature.curr_nozzle < info.temperature.target_nozzle - 5:
        return "Heating Hotend"

    if info.temperature.target_bed > 0 and info.temperature.curr_bed < info.temperature.target_bed - 5:
        return "Heating Bed"

    if project.state == "printing" and project.pause == PauseState.PAUSING:
        return "Pausing"

    if project.state == "printing" and project.pause == PauseState.RESUMING:
        return "Resuming"

    return None


@dataclass
class JobStatus:
    """OE-compatible job status dict.  Use :meth:`to_dict` for the wire format."""
    State: str = STATE_IDLE
    SubState: Optional[str] = None
    Error: Optional[str] = None
    Lights: Optional[list] = None
    CurrentPrint: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "State": self.State,
            "SubState": self.SubState,
            "Error": self.Error,
            "Lights": self.Lights,
        }
        if self.CurrentPrint is not None:
            d["CurrentPrint"] = self.CurrentPrint
        return d


def map_job_status(info: PrinterInfo) -> JobStatus:
    """Convert a Kobra ``PrinterInfo`` to an OE ``JobStatus``."""
    state = _map_state(info)
    sub_state = _map_sub_state(info)
    project = info.project

    current_print = None
    if project is not None and state in (STATE_PRINTING, STATE_PAUSED, STATE_WARMINGUP):
        time_left = min(project.remain_time, OE_INT_MAX) if project.remain_time else 0
        current_print = {
            "Progress": float(project.progress),
            "DurationSec": project.print_time,
            "TimeLeftSec": time_left,
            "FileName": project.filename,
            "EstTotalFilUsedMm": 0,
            "CurrentLayer": project.curr_layer or None,
            "TotalLayers": project.total_layers or None,
            "Temps": {
                "BedActual": info.temperature.curr_bed,
                "BedTarget": info.temperature.target_bed,
                "HotendActual": info.temperature.curr_nozzle,
                "HotendTarget": info.temperature.target_nozzle,
            },
        }

    return JobStatus(
        State=state,
        SubState=sub_state,
        Error=None,
        Lights=None,
        CurrentPrint=current_print,
    )
