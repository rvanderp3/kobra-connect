"""Data models for Moonraker printer objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TemperatureData:
    """Temperature data for extruder or bed."""
    temperature: float = 0.0
    target: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {"temperature": self.temperature, "target": self.target}


@dataclass
class PrintStatsData:
    """Print statistics from print_stats object."""
    state: str = "standby"
    filename: str = ""
    message: str = ""
    progress: float = 0.0
    print_duration: float = 0.0
    total_duration: float = 0.0
    layer: int = 0
    total_layer: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "filename": self.filename,
            "message": self.message,
            "progress": self.progress,
            "print_duration": self.print_duration,
            "total_duration": self.total_duration,
            "layer": self.layer,
            "total_layer": self.total_layer,
        }


@dataclass
class VirtualSDCardData:
    """Virtual SD card data."""
    progress: float = 0.0
    is_printing: bool = False
    file_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "progress": self.progress,
            "is_printing": self.is_printing,
            "file_path": self.file_path,
        }


@dataclass
class WebhooksData:
    """Webhooks state data."""
    state: str = "ready"
    state_message: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"state": self.state, "state_message": self.state_message}


@dataclass
class GCodeMoveData:
    """G-code move data for speed factor."""
    speed_factor: float = 1.0

    def to_dict(self) -> dict[str, float]:
        return {"speed_factor": self.speed_factor}


@dataclass
class ToolheadData:
    """Toolhead position data."""
    position: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])

    def to_dict(self) -> dict[str, list[float]]:
        return {"position": self.position}


@dataclass
class PrinterState:
    """Complete printer state snapshot."""
    print_stats: PrintStatsData = field(default_factory=PrintStatsData)
    virtual_sdcard: VirtualSDCardData = field(default_factory=VirtualSDCardData)
    extruder: TemperatureData = field(default_factory=TemperatureData)
    heater_bed: TemperatureData = field(default_factory=TemperatureData)
    webhooks: WebhooksData = field(default_factory=WebhooksData)
    gcode_move: GCodeMoveData = field(default_factory=GCodeMoveData)
    toolhead: ToolheadData = field(default_factory=ToolheadData)

    def to_query_result(self, objects: dict[str, list[str] | None]) -> dict[str, Any]:
        """Build query result for requested objects."""
        result = {"status": {}}

        if "print_stats" in objects:
            keys = objects["print_stats"] or list(self.print_stats.to_dict().keys())
            result["status"]["print_stats"] = {k: self.print_stats.to_dict().get(k) for k in keys}

        if "virtual_sdcard" in objects:
            keys = objects["virtual_sdcard"] or list(self.virtual_sdcard.to_dict().keys())
            result["status"]["virtual_sdcard"] = {k: self.virtual_sdcard.to_dict().get(k) for k in keys}

        if "extruder" in objects:
            keys = objects["extruder"] or list(self.extruder.to_dict().keys())
            result["status"]["extruder"] = {k: self.extruder.to_dict().get(k) for k in keys}

        if "heater_bed" in objects:
            keys = objects["heater_bed"] or list(self.heater_bed.to_dict().keys())
            result["status"]["heater_bed"] = {k: self.heater_bed.to_dict().get(k) for k in keys}

        if "webhooks" in objects:
            keys = objects["webhooks"] or list(self.webhooks.to_dict().keys())
            result["status"]["webhooks"] = {k: self.webhooks.to_dict().get(k) for k in keys}

        if "gcode_move" in objects:
            keys = objects["gcode_move"] or list(self.gcode_move.to_dict().keys())
            result["status"]["gcode_move"] = {k: self.gcode_move.to_dict().get(k) for k in keys}

        if "toolhead" in objects:
            keys = objects["toolhead"] or list(self.toolhead.to_dict().keys())
            result["status"]["toolhead"] = {k: self.toolhead.to_dict().get(k) for k in keys}

        return result

    def to_subscribe_result(self, objects: dict[str, list[str] | None]) -> dict[str, Any]:
        """Build initial subscribe result (same format as query)."""
        return self.to_query_result(objects)