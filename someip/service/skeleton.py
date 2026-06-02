"""SOME/IP Skeleton (service server implementation).

The Skeleton receives incoming requests, dispatches them to registered
handler methods, and sends back responses.
"""

import asyncio
import logging
from typing import Callable, Dict, Optional

from ..config.service_config import ServiceInterfaceConfig
from ..error import MethodNotFoundError
from ..message.message import SomeipMessage
from ..message.message_type import MessageType
from ..message.return_code import ReturnCode
from .base import ServiceInterface
from .event import Event
from .eventgroup import EventGroup
from .field import Field

logger = logging.getLogger(__name__)


class Skeleton(ServiceInterface):
    """SOME/IP service Skeleton (server side).

    Usage:
        config = ServiceInterfaceConfig(service_id=0x1234, instance_id=0x0001)
        skeleton = Skeleton(config)
        skeleton.register_method(0x0001, my_handler)
        # When a request arrives with method_id=0x0001, my_handler is called
    """

    def __init__(self, config: ServiceInterfaceConfig):
        super().__init__(config)
        # Method handlers: method_id -> async callable(request: SomeipMessage) -> SomeipMessage
        self._method_handlers: Dict[int, Callable] = {}
        # Events
        self._events: Dict[int, Event] = {}
        # Fields
        self._fields: Dict[int, Field] = {}
        # EventGroups
        self._eventgroups: Dict[int, EventGroup] = {}

    def register_method(self, method_id: int, handler: Callable) -> None:
        """Register a handler for a method.

        Handler signature: async handler(request: SomeipMessage) -> bytes
        The return value is the response payload.
        """
        self._method_handlers[method_id] = handler

    def unregister_method(self, method_id: int) -> None:
        """Unregister a method handler."""
        self._method_handlers.pop(method_id, None)

    def register_event(self, event_id: int) -> Event:
        """Register an event and return the Event object."""
        event = Event(self.service_id, event_id)
        self._events[event_id] = event
        return event

    def register_field(self, field_id: int, **kwargs) -> Field:
        """Register a field and return the Field object."""
        field = Field(self.service_id, field_id, **kwargs)
        self._fields[field_id] = field
        return field

    def register_eventgroup(self, eventgroup_id: int) -> EventGroup:
        """Register an eventgroup and return the EventGroup object."""
        eg = EventGroup(self.service_id, self.instance_id, eventgroup_id)
        self._eventgroups[eventgroup_id] = eg
        return eg

    def get_event(self, event_id: int) -> Optional[Event]:
        """Get an event by ID."""
        return self._events.get(event_id)

    def get_field(self, field_id: int) -> Optional[Field]:
        """Get a field by ID."""
        return self._fields.get(field_id)

    def get_eventgroup(self, eventgroup_id: int) -> Optional[EventGroup]:
        """Get an eventgroup by ID."""
        return self._eventgroups.get(eventgroup_id)

    async def handle_message(self, message: SomeipMessage) -> Optional[SomeipMessage]:
        """Handle an incoming SOME/IP message.

        Returns the response message, or None for fire-and-forget.
        """
        msg_type = message.header.message_type

        if msg_type == MessageType.REQUEST:
            return await self._handle_request(message)
        elif msg_type == MessageType.REQUEST_NO_RETURN:
            await self._handle_fire_and_forget(message)
            return None
        else:
            logger.warning(
                "Skeleton received unexpected message type: %s", msg_type
            )
            return None

    async def _handle_request(self, request: SomeipMessage) -> SomeipMessage:
        """Handle a request message (expects a response)."""
        method_id = request.header.method_id

        # Check if it's a field getter/setter
        for field in self._fields.values():
            if method_id == field.getter_id:
                return await field.handle_get(request)
            elif method_id == field.setter_id:
                return await field.handle_set(request)

        # Check method handlers
        handler = self._method_handlers.get(method_id)
        if handler:
            try:
                result_payload = await handler(request)
                if isinstance(result_payload, SomeipMessage):
                    return result_payload
                return SomeipMessage.build_response(
                    request=request,
                    interface_version=self.interface_version,
                    payload=result_payload,
                    return_code=ReturnCode.E_OK,
                )
            except Exception as e:
                logger.error("Method handler error for 0x%04X: %s", method_id, e)
                return SomeipMessage.build_error(
                    request=request,
                    interface_version=self.interface_version,
                    return_code=ReturnCode.E_NOT_OK,
                )

        # Method not found
        return SomeipMessage.build_error(
            request=request,
            interface_version=self.interface_version,
            return_code=ReturnCode.E_UNKNOWN_METHOD,
        )

    async def _handle_fire_and_forget(self, request: SomeipMessage) -> None:
        """Handle a fire-and-forget request (no response expected)."""
        method_id = request.header.method_id
        handler = self._method_handlers.get(method_id)
        if handler:
            try:
                await handler(request)
            except Exception as e:
                logger.error(
                    "Fire&forget handler error for 0x%04X: %s", method_id, e
                )
