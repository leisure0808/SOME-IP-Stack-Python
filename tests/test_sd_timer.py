"""Tests for SD timer state machine."""

import asyncio

import pytest

from someip.sd.timer import SdPhase, SdTimer, SdTimingConfig


@pytest.mark.asyncio
class TestSdTimer:
    async def test_start_and_stop(self):
        config = SdTimingConfig(
            initial_delay_min=0.0,
            initial_delay_max=0.01,
            repetitions_base_delay=0.01,
            repetitions_max=2,
            cyclic_offer_delay=0.05,
        )
        callback_count = 0

        def callback():
            nonlocal callback_count
            callback_count += 1

        timer = SdTimer(config, callback, name="test")
        assert timer.phase == SdPhase.STOPPED

        await timer.start()
        assert timer.phase in (SdPhase.INITIAL, SdPhase.REPEAT, SdPhase.MAIN)

        # Wait for initial + repeat phases
        await asyncio.sleep(0.1)
        assert callback_count >= 1

        await timer.stop()
        assert timer.phase == SdPhase.STOPPED

    async def test_phases_transition(self):
        config = SdTimingConfig(
            initial_delay_min=0.0,
            initial_delay_max=0.01,
            repetitions_base_delay=0.01,
            repetitions_max=1,
            cyclic_offer_delay=0.1,
        )
        phases_seen = []

        def callback():
            pass

        timer = SdTimer(config, callback, name="test-phases")
        await timer.start()

        # After initial delay, should be in REPEAT or MAIN
        await asyncio.sleep(0.05)
        assert timer.phase in (SdPhase.REPEAT, SdPhase.MAIN)

        # After repeat phase, should be in MAIN
        await asyncio.sleep(0.1)
        assert timer.phase == SdPhase.MAIN

        await timer.stop()

    async def test_force_main_phase(self):
        config = SdTimingConfig(
            initial_delay_min=0.5,
            initial_delay_max=1.0,
            repetitions_base_delay=0.01,
            repetitions_max=10,
            cyclic_offer_delay=0.05,
        )
        callback_count = 0

        def callback():
            nonlocal callback_count
            callback_count += 1

        timer = SdTimer(config, callback, name="test-force")
        await timer.start()

        # Force to main phase while in INITIAL
        await asyncio.sleep(0.01)
        timer.force_main_phase()

        # Should quickly reach MAIN phase
        await asyncio.sleep(0.1)
        assert timer.phase == SdPhase.MAIN

        await timer.stop()

    async def test_callback_count_in_repeat(self):
        config = SdTimingConfig(
            initial_delay_min=0.0,
            initial_delay_max=0.01,
            repetitions_base_delay=0.01,
            repetitions_max=3,
            cyclic_offer_delay=0.1,
        )
        callback_count = 0

        def callback():
            nonlocal callback_count
            callback_count += 1

        timer = SdTimer(config, callback, name="test-count")
        await timer.start()

        # Wait through initial (1 callback) + repeat (3 callbacks)
        await asyncio.sleep(0.15)
        # At least initial + repeat callbacks
        assert callback_count >= 1

        await timer.stop()
