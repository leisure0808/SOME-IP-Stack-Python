"""SOME/IP event management."""

import asyncio
import logging
from typing import Callable, Dict, List, Optional, Set

from ..message.message import SomeipMessage
from ..message.return_code import ReturnCode

logger = logging.getLogger(__name__)


class Event:
    """Manages a SOME/IP event.

    Events are notification messages sent from service to subscribers.
    Events belong to eventgroups and are sent when the event data changes.
    """

    def __init__(self, service_id: int, event_id: int):
        self._service_id = service_id
        self._event_id = event_id
        self._subscribers: Dict[tuple, asyncio.Queue] = {}
        self._handlers: List[Callable] = []

    @property
    def service_id(self) -> int:
        return self._service_id

    @property
    def event_id(self) -> int:
        return self._event_id

    def add_subscriber(self, client_id: int, session_id: int) -> asyncio.Queue:
        """Add a subscriber and return a queue they can consume events from."""
        key = (client_id, session_id)
        if key not in self._subscribers:
            self._subscribers[key] = asyncio.Queue()
        return self._subscribers[key]

    def remove_subscriber(self, client_id: int, session_id: int) -> None:
        """Remove a subscriber."""
        self._subscribers.pop((client_id, session_id), None)

    def add_handler(self, handler: Callable) -> None:
        """Add a callback handler for this event."""
        self._handlers.append(handler)

    @property
    def has_subscribers(self) -> bool:
        return len(self._subscribers) > 0 or len(self._handlers) > 0

    async def notify(self, payload: bytes, client_id: int = 0, session_id: int = 0) -> None:
        """Send a notification to all subscribers."""
        msg = SomeipMessage.build_notification(
            service_id=self._service_id,
            event_id=self._event_id,
            client_id=client_id,
            session_id=session_id,
            interface_version=0x01,
            payload=payload,
        )

        # Push to subscriber queues
        for queue in self._subscribers.values():
            await queue.put(msg)

        # Call handlers
        for handler in self._handlers:
            try:
                handler(msg)
            except Exception as e:
                logger.warning("Event handler error: %s", e)
