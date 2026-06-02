"""Async utility functions."""

import asyncio
from typing import Any, Coroutine


async def wait_for_any(*coros: Coroutine, timeout: float = 5.0) -> Any:
    """Wait for any of the given coroutines to complete."""
    tasks = [asyncio.create_task(c) for c in coros]
    try:
        done, pending = await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in pending:
            try:
                await t
            except asyncio.CancelledError:
                pass
        if done:
            return next(iter(done)).result()
        raise asyncio.TimeoutError()
    except asyncio.TimeoutError:
        for t in tasks:
            t.cancel()
        raise
