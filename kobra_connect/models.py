"""Data models for Kobra 3 printer state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class PauseState(IntEnum):
    PRINTING = 0
    PAUSED = 1
    PAUSING = 2
    RESUMING = 3
    STOPPING = 4


@dataclass(frozen=True)
class Temperature:
    curr_nozzle: float
    target_nozzle: float
    curr_bed: float
    target_bed: float

    @classmethod
    def from_dict(cls, d: dict) -> Temperature:
        return cls(
            curr_nozzle=d["curr_nozzle_temp"],
            target_nozzle=d["target_nozzle_temp"],
            curr_bed=d["curr_hotbed_temp"],
            target_bed=d["target_hotbed_temp"],
        )


@dataclass(frozen=True)
class PrintProject:
    state: str
    filename: str
    progress: int
    curr_layer: int
    total_layers: int
    remain_time: int
    print_time: int
    pause: int
    task_id: int | None = None
    print_speed_mode: int | None = None

    @property
    def is_printing(self) -> bool:
        return self.state == "printing" and self.pause == PauseState.PRINTING

    @property
    def is_paused(self) -> bool:
        return self.pause == PauseState.PAUSED

    @classmethod
    def from_dict(cls, d: dict) -> PrintProject:
        return cls(
            state=d.get("state", ""),
            filename=d.get("filename", ""),
            progress=d.get("progress", 0),
            curr_layer=d.get("curr_layer", 0),
            total_layers=d.get("total_layers", 0),
            remain_time=d.get("remain_time", 0),
            print_time=d.get("print_time", 0),
            pause=d.get("pause", 0),
            task_id=d.get("task_id"),
            print_speed_mode=d.get("print_speed_mode"),
        )


@dataclass(frozen=True)
class PrinterInfo:
    name: str
    model: str
    model_id: int
    ip: str
    firmware: str
    state: str
    temperature: Temperature
    fan_speed_pct: int
    aux_fan_speed_pct: int
    box_fan_level: int
    print_speed_mode: int
    project: PrintProject | None
    features: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> PrinterInfo:
        project = None
        if d.get("project"):
            project = PrintProject.from_dict(d["project"])
        return cls(
            name=d.get("printerName", ""),
            model=d.get("model", ""),
            model_id=d.get("modelId", 0),
            ip=d.get("ip", ""),
            firmware=d.get("version", ""),
            state=d.get("state", ""),
            temperature=Temperature.from_dict(d.get("temp", {})),
            fan_speed_pct=d.get("fan_speed_pct", 0),
            aux_fan_speed_pct=d.get("aux_fan_speed_pct", 0),
            box_fan_level=d.get("box_fan_level", 0),
            print_speed_mode=d.get("print_speed_mode", 0),
            project=project,
            features=d.get("features", {}),
        )


@dataclass(frozen=True)
class FanSpeed:
    part_cooling: int
    aux: int
    box: int

    @classmethod
    def from_dict(cls, d: dict) -> FanSpeed:
        return cls(
            part_cooling=d.get("fan_speed_pct", 0),
            aux=d.get("aux_fan_speed_pct", 0),
            box=d.get("box_fan_level", 0),
        )


@dataclass(frozen=True)
class HandshakeResult:
    broker_host: str
    broker_port: int
    username: str
    password: str
    device_id: str
    model_id: str
    serial: str
    device_cert: str
    device_key: str
    mac: str | None = None
    model_name: str | None = None
    device_type: str | None = None
