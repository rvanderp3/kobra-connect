"""OE IPrinterStateReporter implementation for Kobra 3."""

from __future__ import annotations

from typing import Optional, Tuple

from .interfaces import IPrinterStateReporter
from .state_translator import KobraStateTranslator


class KobraStateReporter(IPrinterStateReporter):

    def __init__(self, translator: KobraStateTranslator) -> None:
        self._translator = translator

    def GetPrintTimeRemainingEstimateInSeconds(self) -> int:
        info = self._translator.get_info()
        if info is None or info.project is None:
            return 0
        remain = info.project.remain_time
        return remain if remain > 0 else 0

    def GetCurrentZOffsetMm(self) -> int:
        return 0

    def GetCurrentLayerInfo(self) -> Tuple[Optional[int], Optional[int]]:
        info = self._translator.get_info()
        if info is None or info.project is None:
            return (None, None)
        return (info.project.curr_layer, info.project.total_layers)

    def ShouldPrintingTimersBeRunning(self) -> bool:
        info = self._translator.get_info()
        if info is None or info.project is None:
            return False
        return info.project.is_printing

    def IsPrintWarmingUp(self) -> bool:
        temp = self._translator.get_temperature()
        if temp is None:
            return False
        if temp.target_nozzle > 0 and temp.curr_nozzle < temp.target_nozzle - 10:
            return True
        if temp.target_bed > 0 and temp.curr_bed < temp.target_bed - 10:
            return True
        return False

    def GetTemps(self) -> Tuple[Optional[float], Optional[float]]:
        temp = self._translator.get_temperature()
        if temp is None:
            return (None, None)
        return (temp.curr_bed, temp.curr_nozzle)
