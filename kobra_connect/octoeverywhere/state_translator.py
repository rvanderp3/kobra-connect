"""Listens to Kobra MQTT reports and maintains a live state snapshot."""

from __future__ import annotations

import logging
import threading
from typing import Optional

from ..client import KobraClient
from ..models import FanSpeed, PrinterInfo, Temperature
from .models import JobStatus, map_job_status

logger = logging.getLogger(__name__)


class KobraStateTranslator:
    """Subscribes to Kobra MQTT reports and keeps a live ``PrinterInfo`` snapshot.

    The translator installs an ``on_report`` callback on the
    :class:`~kobra_connect.KobraClient` and incrementally updates a
    thread-safe state model that can be queried by the command handler and
    state reporter.
    """

    def __init__(self, client: KobraClient) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._info: Optional[PrinterInfo] = None
        self._temperature: Optional[Temperature] = None
        self._fan_speed: Optional[FanSpeed] = None

        # Wire up the MQTT report callback
        self._client.on_report = self._on_report

    # -- public query API ----------------------------------------------------

    def get_info(self) -> Optional[PrinterInfo]:
        """Return the latest ``PrinterInfo`` (or ``None`` if not yet received)."""
        with self._lock:
            return self._info

    def get_temperature(self) -> Optional[Temperature]:
        with self._lock:
            return self._temperature

    def get_fan_speed(self) -> Optional[FanSpeed]:
        with self._lock:
            return self._fan_speed

    def get_job_status(self) -> JobStatus:
        """Return the current job status in OE dict format."""
        info = self.get_info()
        if info is None:
            return JobStatus()
        return map_job_status(info)

    # -- MQTT callback -------------------------------------------------------

    def _on_report(self, topic: str, data: dict) -> None:
        try:
            self._process_report(topic, data)
        except Exception:
            logger.debug("Failed to process report on %s", topic, exc_info=True)

    def _process_report(self, topic: str, data: dict) -> None:
        """Dispatch an incoming report to the appropriate model updater."""
        report_data = data.get("data", data)
        msg_type = data.get("type", "")

        with self._lock:
            if msg_type == "info" or self._is_info_topic(topic):
                self._update_info(report_data)
            elif msg_type == "tempature" or self._is_temp_topic(topic):
                self._update_temperature(report_data)
            elif msg_type == "fan" or self._is_fan_topic(topic):
                self._update_fan_speed(report_data)

    def _update_info(self, raw: dict) -> None:
        if self._info is None:
            self._info = PrinterInfo.from_dict(raw)
        else:
            self._info = PrinterInfo.from_dict(raw)
        logger.debug("Info updated: %s state=%s", self._info.name, self._info.state)

    def _update_temperature(self, raw: dict) -> None:
        self._temperature = Temperature.from_dict(raw)

    def _update_fan_speed(self, raw: dict) -> None:
        self._fan_speed = FanSpeed.from_dict(raw)

    # -- topic matching helpers ----------------------------------------------

    @staticmethod
    def _is_info_topic(topic: str) -> bool:
        return "/info/report" in topic

    @staticmethod
    def _is_temp_topic(topic: str) -> bool:
        return "/tempature/report" in topic

    @staticmethod
    def _is_fan_topic(topic: str) -> bool:
        return "/fan/report" in topic
