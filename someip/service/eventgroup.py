"""SOME/IP eventgroup subscription management."""

import logging
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class EventGroup:
    """Manages a SOME/IP event group.

    An event group is a collection of events that can be subscribed to
    as a group via the Service Discovery SubscribeEventGroup mechanism.
    """

    def __init__(self, service_id: int, instance_id: int, eventgroup_id: int):
        self._service_id = service_id
        self._instance_id = instance_id
        self._eventgroup_id = eventgroup_id
        self._event_ids: Set[int] = set()
        self._subscribers: Dict[tuple, dict] = {}  # (client_id, session_id) -> {}

    @property
    def eventgroup_id(self) -> int:
        return self._eventgroup_id

    @property
    def event_ids(self) -> Set[int]:
        return self._event_ids

    def add_event(self, event_id: int) -> None:
        """Add an event to this group."""
        self._event_ids.add(event_id)

    def remove_event(self, event_id: int) -> None:
        """Remove an event from this group."""
        self._event_ids.discard(event_id)

    def add_subscriber(self, client_id: int, session_id: int) -> None:
        """Add a subscriber to this event group."""
        key = (client_id, session_id)
        if key not in self._subscribers:
            self._subscribers[key] = {}

    def remove_subscriber(self, client_id: int, session_id: int) -> None:
        """Remove a subscriber from this event group."""
        self._subscribers.pop((client_id, session_id), None)

    @property
    def has_subscribers(self) -> bool:
        return len(self._subscribers) > 0

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
