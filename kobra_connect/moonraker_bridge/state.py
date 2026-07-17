"""Moonraker printer object state models for the bridge."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PrintStats:
    """print_stats printer object - print state and progress.
    
    Matches Moonraker/Klipper print_stats object format:
    {
        "filename": "",
        "total_duration": 0.0,
        "print_duration": 0.0,
        "filament_used": 0.0,
        "state": "standby",
        "message": "",
        "info": {
            "total_layer": null,
            "current_layer": null
        }
    }
    """

    state: str = "standby"
    filename: str = ""
    message: str = ""
    progress: float = 0.0
    print_duration: float = 0.0
    total_duration: float = 0.0
    print_time_left: float = 0.0
    filament_used: float = 0.0
    # Layer info goes in "info" object
    current_layer: int = 0
    total_layer: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "filename": self.filename,
            "message": self.message,
            "progress": self.progress,
            "print_duration": self.print_duration,
            "total_duration": self.total_duration,
            "print_time_left": self.print_time_left,
            "filament_used": self.filament_used,
            "info": {
                "total_layer": self.total_layer,
                "current_layer": self.current_layer,
            }
        }


@dataclass
class VirtualSdcard:
    """virtual_sdcard printer object - SD card print progress."""

    progress: float = 0.0
    is_active: bool = False
    file_position: int = 0
    file_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "progress": self.progress,
            "is_active": self.is_active,
            "file_position": self.file_position,
            "file_size": self.file_size,
        }


@dataclass
class Extruder:
    """extruder printer object - hotend temperature."""

    temperature: float = 0.0
    target: float = 0.0
    power: float = 0.0
    can_extrude: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "target": self.target,
            "power": self.power,
            "can_extrude": self.can_extrude,
        }


@dataclass
class HeaterBed:
    """heater_bed printer object - bed temperature."""

    temperature: float = 0.0
    target: float = 0.0
    power: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "target": self.target,
            "power": self.power,
        }


@dataclass
class Webhooks:
    """webhooks printer object - printer connection state."""

    state: str = "ready"
    state_message: str = "Printer is ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "state_message": self.state_message,
        }


@dataclass
class GcodeMove:
    """gcode_move printer object - motion state."""

    speed_factor: float = 1.0
    extrude_factor: float = 1.0
    absolute_coord: bool = True
    absolute_extrude: bool = True
    homing_origin: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    position: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])

    def to_dict(self) -> dict[str, Any]:
        return {
            "speed_factor": self.speed_factor,
            "extrude_factor": self.extrude_factor,
            "absolute_coord": self.absolute_coord,
            "absolute_extrude": self.absolute_extrude,
            "homing_origin": self.homing_origin,
            "position": self.position,
        }


@dataclass
class Toolhead:
    """toolhead printer object - toolhead position and status."""

    position: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    status: str = "Ready"
    homed_axes: str = "xyz"
    max_velocity: float = 0.0
    max_accel: float = 0.0
    max_accel_to_decel: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "status": self.status,
            "homed_axes": self.homed_axes,
            "max_velocity": self.max_velocity,
            "max_accel": self.max_accel,
            "max_accel_to_decel": self.max_accel_to_decel,
        }


class TemperatureStore:
    """Ring-buffer of temperature readings for Moonraker's temperature_store.

    Moonraker format per sensor:
    { "temperatures": [...], "targets": [...], "powers": [...] }
    Each entry is [timestamp, value].
    """

    MAXLEN = 1200  # ~20 min at 1 Hz

    def __init__(self) -> None:
        self.extruder_temps: deque[list] = deque(maxlen=self.MAXLEN)
        self.extruder_targets: deque[list] = deque(maxlen=self.MAXLEN)
        self.bed_temps: deque[list] = deque(maxlen=self.MAXLEN)
        self.bed_targets: deque[list] = deque(maxlen=self.MAXLEN)

    def append(self, extruder_temp: float, extruder_target: float,
               bed_temp: float, bed_target: float) -> None:
        ts = time.time()
        self.extruder_temps.append([ts, extruder_temp])
        self.extruder_targets.append([ts, extruder_target])
        self.bed_temps.append([ts, bed_temp])
        self.bed_targets.append([ts, bed_target])

    def to_dict(self) -> dict[str, Any]:
        return {
            "extruder": {
                "temperatures": list(self.extruder_temps),
                "targets": list(self.extruder_targets),
                "powers": [],
            },
            "heater_bed": {
                "temperatures": list(self.bed_temps),
                "targets": list(self.bed_targets),
                "powers": [],
            },
        }


class MoonrakerState:
    """Aggregates all printer object states and builds Moonraker query responses."""

    def __init__(self) -> None:
        self.print_stats = PrintStats()
        self.virtual_sdcard = VirtualSdcard()
        self.extruder = Extruder()
        self.heater_bed = HeaterBed()
        self.webhooks = Webhooks()
        self.gcode_move = GcodeMove()
        self.toolhead = Toolhead()
        self.temperature_store = TemperatureStore()
        self._frozen_total_duration: float = 0.0
        self._frozen_filename: str = ""

    def update_from_kobra_info(self, info: Any) -> None:
        """Update state from Kobra PrinterInfo."""
        # Map Kobra state to Moonraker print_stats state.
        # Use project.state when a project exists (it reflects the actual print
        # job state), fall back to info.state otherwise.
        state_map = {
            "printing": "printing",
            "paused": "paused",
            "idle": "standby",
            "preparing": "standby",
            "heating": "standby",
            "leveling": "standby",
            "finish": "complete",
            "error": "error",
            "cancelled": "cancelled",
        }
        kobra_state = ""
        if info.project:
            kobra_state = info.project.state.lower()
            # Pause overrides printing state
            if kobra_state == "printing" and info.project.pause in (1, 2):  # PAUSED, PAUSING
                kobra_state = "paused"
            elif kobra_state == "printing" and info.project.pause == 4:  # STOPPING
                kobra_state = "cancelled"
        elif info.state:
            kobra_state = info.state.lower()
        self.print_stats.state = state_map.get(kobra_state, "standby")

        # Project info
        if info.project:
            self.print_stats.filename = info.project.filename or ""
            self.print_stats.current_layer = info.project.curr_layer or 0
            self.print_stats.total_layer = info.project.total_layers or 0

            # Kobra MQTT reports print_time and remain_time in MINUTES.
            # Moonraker/Klipper expect SECONDS — convert here.
            kobra_print_min = info.project.print_time or 0
            kobra_remain_min = info.project.remain_time or 0
            print_sec = float(kobra_print_min * 60)
            remain_sec = float(kobra_remain_min * 60)

            # Derive progress from time ratio for sub-percent precision
            # (Kobra's progress field is integer 0-100)
            total_min = kobra_print_min + kobra_remain_min
            if total_min > 0:
                self.print_stats.progress = kobra_print_min / total_min
            else:
                self.print_stats.progress = info.project.progress / 100.0 if info.project.progress else 0.0

            self.print_stats.print_duration = print_sec
            self.virtual_sdcard.progress = self.print_stats.progress
            self.virtual_sdcard.is_active = info.project.state == "printing"

            # Estimated total print time (current + remaining).
            # Freeze total_duration when a print starts — Klipper sets this
            # once from the slicer estimate and keeps it constant.  The OE
            # companion computes remaining = total_duration - print_duration,
            # so a fluctuating total causes the displayed time to oscillate.
            if info.project.state == "printing":
                computed_total = print_sec + remain_sec
                # Freeze on new print or first update
                if self._frozen_filename != info.project.filename or self._frozen_total_duration <= 0.0:
                    self._frozen_total_duration = computed_total
                    self._frozen_filename = info.project.filename
                self.print_stats.total_duration = self._frozen_total_duration
            else:
                # Not printing — reset so next print gets a fresh freeze
                self._frozen_total_duration = 0.0
                self._frozen_filename = ""
                self.print_stats.total_duration = print_sec + remain_sec
            self.print_stats.print_time_left = remain_sec if remain_sec > 0 else 0.0

            # Filament used not available from Kobra
            self.print_stats.filament_used = 0.0

        # Temperatures
        self.extruder.temperature = info.temperature.curr_nozzle
        self.extruder.target = info.temperature.target_nozzle
        self.heater_bed.temperature = info.temperature.curr_bed
        self.heater_bed.target = info.temperature.target_bed

        # Update webhooks based on print state
        if self.print_stats.state == "printing":
            self.webhooks.state = "printing"
            self.webhooks.state_message = "Printing"
        elif self.print_stats.state == "paused":
            self.webhooks.state = "paused"
            self.webhooks.state_message = "Paused"
        elif self.print_stats.state == "complete":
            self.webhooks.state = "ready"
            self.webhooks.state_message = "Print complete"
        elif self.print_stats.state == "error":
            self.webhooks.state = "error"
            self.webhooks.state_message = "Print error"
        else:
            self.webhooks.state = "ready"
            self.webhooks.state_message = "Printer is ready"

    def update_from_kobra_temperature(self, temp: Any) -> None:
        """Update state from Kobra Temperature."""
        self.extruder.temperature = temp.curr_nozzle
        self.extruder.target = temp.target_nozzle
        self.heater_bed.temperature = temp.curr_bed
        self.heater_bed.target = temp.target_bed
        self.temperature_store.append(
            temp.curr_nozzle, temp.target_nozzle,
            temp.curr_bed, temp.target_bed,
        )

    def to_query_result(self, objects: dict[str, Any]) -> dict[str, Any]:
        """Build printer.objects.query response."""
        status: dict[str, Any] = {}

        for obj_name, fields in objects.items():
            obj = getattr(self, obj_name, None)
            if obj is None:
                continue

            obj_dict = obj.to_dict()
            if fields is None:
                # All fields
                status[obj_name] = obj_dict
            elif isinstance(fields, list):
                # Specific fields
                status[obj_name] = {k: v for k, v in obj_dict.items() if k in fields}
            else:
                status[obj_name] = obj_dict

        return {"status": status}

    def to_subscribe_result(self, objects: dict[str, Any]) -> dict[str, Any]:
        """Build printer.objects.subscribe response (same format as query but returns initial state)."""
        return self.to_query_result(objects)