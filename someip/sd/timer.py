"""SOME/IP Service Discovery timer state machine.

SD follows a three-phase timing model:
1. INITIAL phase: Initial delay before first offer
2. REPEAT phase: Rapid repetitions with short intervals
3. MAIN phase: Regular heartbeat at longer intervals
"""

import asyncio
import random
import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class SdPhase(Enum):
    """SD timer phase."""

    INITIAL = auto()
    REPEAT = auto()
    MAIN = auto()
    STOPPED = auto()


@dataclass
class SdTimingConfig:
    """SD timing configuration (all values in seconds).

    Default values per AUTOSAR SOME/IP Service Discovery Protocol specification.
    """

    # Initial phase: random delay before first offer/find
    initial_delay_min: float = 0.1   # 100ms per spec
    initial_delay_max: float = 1.0   # 1000ms per spec

    # Repeat phase: rapid repetitions
    repetitions_base_delay: float = 0.03  # 30ms per spec
    repetitions_max: int = 5              # 5 repetitions per spec

    # Main phase: regular heartbeat
    cyclic_offer_delay: float = 1.0  # 1 second per spec

    # Request response delay
    request_response_delay: float = 1.5  # 1.5 seconds


class SdTimer:
    """SD timer state machine for controlling offer/find message timing.

    Usage:
        timer = SdTimer(config, callback)
        await timer.start()  # Starts INITIAL phase
        # ... timer automatically transitions through phases
        await timer.stop()   # Stops all timers
    """

    def __init__(
        self,
        config: SdTimingConfig,
        callback: Callable[[], None],
        name: str = "SdTimer",
    ):
        self._config = config
        self._callback = callback
        self._name = name
        self._phase = SdPhase.STOPPED
        self._repeat_count = 0
        self._task: Optional[asyncio.Task] = None

    @property
    def phase(self) -> SdPhase:
        return self._phase

    async def start(self) -> None:
        """Start the SD timer from INITIAL phase."""
        if self._phase != SdPhase.STOPPED:
            return

        self._repeat_count = 0
        self._phase = SdPhase.INITIAL
        self._task = asyncio.create_task(self._run(), name=self._name)
        logger.debug("SD timer '%s' started", self._name)

    async def stop(self) -> None:
        """Stop the SD timer."""
        self._phase = SdPhase.STOPPED
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.debug("SD timer '%s' stopped", self._name)

    def force_main_phase(self) -> None:
        """Skip directly to MAIN phase (e.g., after receiving a FindService)."""
        if self._phase in (SdPhase.INITIAL, SdPhase.REPEAT, SdPhase.MAIN):
            if self._phase == SdPhase.MAIN:
                return
            self._phase = SdPhase.MAIN
            self._repeat_count = 0
            # Cancel current task so it breaks out of sleep
            if self._task and not self._task.done():
                self._task.cancel()
                # Create a new task that will enter _main_phase directly
                self._task = asyncio.create_task(self._run(), name=self._name)

    async def _run(self) -> None:
        """Main timer loop."""
        try:
            if self._phase == SdPhase.INITIAL:
                await self._initial_phase()
                if self._phase == SdPhase.STOPPED:
                    return

            if self._phase == SdPhase.REPEAT:
                await self._repeat_phase()
                if self._phase == SdPhase.STOPPED:
                    return

            if self._phase == SdPhase.MAIN:
                await self._main_phase()
        except asyncio.CancelledError:
            pass

    async def _initial_phase(self) -> None:
        """Initial delay before first offer."""
        delay = random.uniform(
            self._config.initial_delay_min,
            self._config.initial_delay_max,
        )
        self._phase = SdPhase.INITIAL
        logger.debug("SD timer INITIAL phase: %.3fs delay", delay)

        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            if self._phase == SdPhase.STOPPED:
                raise
            # Cancelled by force_main_phase, return to let next phase start
            return

        if self._phase == SdPhase.INITIAL:
            self._callback()
            self._phase = SdPhase.REPEAT

    async def _repeat_phase(self) -> None:
        """Rapid repetition phase."""
        for i in range(self._config.repetitions_max):
            if self._phase == SdPhase.STOPPED:
                return
            if self._phase == SdPhase.MAIN:
                return  # Forced to main phase

            try:
                await asyncio.sleep(self._config.repetitions_base_delay)
            except asyncio.CancelledError:
                if self._phase == SdPhase.STOPPED:
                    raise
                return  # Forced to main phase

            if self._phase == SdPhase.REPEAT:
                self._callback()
                self._repeat_count += 1

        if self._phase == SdPhase.REPEAT:
            self._phase = SdPhase.MAIN

    async def _main_phase(self) -> None:
        """Regular cyclic offer phase."""
        logger.debug("SD timer MAIN phase: %.1fs interval", self._config.cyclic_offer_delay)

        while self._phase == SdPhase.MAIN:
            self._callback()

            try:
                await asyncio.sleep(self._config.cyclic_offer_delay)
            except asyncio.CancelledError:
                if self._phase == SdPhase.STOPPED:
                    raise
                return
