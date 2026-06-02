"""Tests for Event."""

import asyncio

import pytest

from someip.message.message import SomeipMessage
from someip.service.event import Event


@pytest.mark.asyncio
class TestEvent:
    async def test_notify_subscribers(self):
        event = Event(service_id=0x1234, event_id=0x8001)
        queue = event.add_subscriber(client_id=0x0001, session_id=0x0001)

        await event.notify(b"\xDE\xAD", client_id=0x0001, session_id=0x0001)

        msg = await asyncio.wait_for(queue.get(), timeout=0.5)
        assert msg.payload == b"\xDE\xAD"
        assert msg.header.service_id == 0x1234

    async def test_handler(self):
        event = Event(service_id=0x1234, event_id=0x8001)
        received = []

        event.add_handler(lambda msg: received.append(msg))

        await event.notify(b"\x01\x02", client_id=0x0000, session_id=0x0001)

        assert len(received) == 1
        assert received[0].payload == b"\x01\x02"

    async def test_no_subscribers(self):
        event = Event(service_id=0x1234, event_id=0x8001)
        # Should not raise
        await event.notify(b"\x00", client_id=0x0000, session_id=0x0001)
