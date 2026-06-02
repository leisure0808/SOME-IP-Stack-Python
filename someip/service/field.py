"""SOME/IP field (getter/setter/notifier) management."""

import asyncio
import logging
from typing import Callable, Optional

from ..message.message import SomeipMessage
from ..message.message_type import MessageType
from ..message.return_code import ReturnCode

logger = logging.getLogger(__name__)


class Field:
    """Manages a SOME/IP field.

    A field has up to three aspects:
    - Getter (method_id = field_id + 0x0000): Read the field value
    - Setter (method_id = field_id + 0x0001): Write the field value
    - Notifier (event_id = field_id): Receive notifications on change

    Method IDs for field getter/setter use the same base ID as the field
    with an offset of +1 for the setter.
    """

    def __init__(
        self,
        service_id: int,
        field_id: int,
        getter_id: Optional[int] = None,
        setter_id: Optional[int] = None,
        notifier_id: Optional[int] = None,
    ):
        self._service_id = service_id
        self._field_id = field_id
        self._getter_id = getter_id if getter_id is not None else field_id
        self._setter_id = setter_id if setter_id is not None else field_id + 1
        self._notifier_id = notifier_id

        self._value: bytes = b""
        self._getter_handler: Optional[Callable] = None
        self._setter_handler: Optional[Callable] = None
        self._notifier_handlers: list = []

    @property
    def field_id(self) -> int:
        return self._field_id

    @property
    def getter_id(self) -> int:
        return self._getter_id

    @property
    def setter_id(self) -> int:
        return self._setter_id

    @property
    def notifier_id(self) -> Optional[int]:
        return self._notifier_id

    @property
    def has_getter(self) -> bool:
        return self._getter_handler is not None

    @property
    def has_setter(self) -> bool:
        return self._setter_handler is not None

    @property
    def has_notifier(self) -> bool:
        return self._notifier_id is not None

    def set_getter_handler(self, handler: Callable) -> None:
        """Set the getter handler. Signature: async handler() -> bytes"""
        self._getter_handler = handler

    def set_setter_handler(self, handler: Callable) -> None:
        """Set the setter handler. Signature: async handler(value: bytes) -> bytes"""
        self._setter_handler = handler

    def add_notifier_handler(self, handler: Callable) -> None:
        """Add a notifier handler. Signature: handler(value: bytes)"""
        self._notifier_handlers.append(handler)

    async def handle_get(self, request: SomeipMessage) -> SomeipMessage:
        """Handle a getter request."""
        if self._getter_handler:
            try:
                value = await self._getter_handler()
                return SomeipMessage.build_response(
                    request=request,
                    interface_version=0x01,
                    payload=value,
                    return_code=ReturnCode.E_OK,
                )
            except Exception as e:
                logger.error("Field getter error: %s", e)
                return SomeipMessage.build_error(
                    request=request,
                    interface_version=0x01,
                    return_code=ReturnCode.E_NOT_OK,
                )
        return SomeipMessage.build_error(
            request=request,
            interface_version=0x01,
            return_code=ReturnCode.E_UNKNOWN_METHOD,
        )

    async def handle_set(self, request: SomeipMessage) -> SomeipMessage:
        """Handle a setter request."""
        if self._setter_handler:
            try:
                result = await self._setter_handler(request.payload)
                # Notify on change if notifier exists
                if self._notifier_id and self._notifier_handlers:
                    for handler in self._notifier_handlers:
                        handler(result)

                return SomeipMessage.build_response(
                    request=request,
                    interface_version=0x01,
                    payload=result,
                    return_code=ReturnCode.E_OK,
                )
            except Exception as e:
                logger.error("Field setter error: %s", e)
                return SomeipMessage.build_error(
                    request=request,
                    interface_version=0x01,
                    return_code=ReturnCode.E_NOT_OK,
                )
        return SomeipMessage.build_error(
            request=request,
            interface_version=0x01,
            return_code=ReturnCode.E_UNKNOWN_METHOD,
        )

    async def notify(self, client_id: int = 0, session_id: int = 0) -> Optional[SomeipMessage]:
        """Build a notification message for this field."""
        if self._notifier_id and self._getter_handler:
            value = await self._getter_handler()
            return SomeipMessage.build_notification(
                service_id=self._service_id,
                event_id=self._notifier_id,
                client_id=client_id,
                session_id=session_id,
                interface_version=0x01,
                payload=value,
            )
        return None
