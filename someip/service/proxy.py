"""SOME/IP Proxy (service client implementation).

The Proxy sends requests to a remote Skeleton and manages
pending request futures for correlating responses.
"""

import asyncio
import logging
from typing import Dict, Optional

from ..config.service_config import ServiceInterfaceConfig
from ..error import TimeoutError as SomeipTimeoutError
from ..message.message import SomeipMessage
from ..message.message_type import MessageType
from ..message.return_code import ReturnCode
from .base import ServiceInterface

logger = logging.getLogger(__name__)


class Proxy(ServiceInterface):
    """SOME/IP service Proxy (client side).

    Usage:
        config = ServiceInterfaceConfig(service_id=0x1234, instance_id=0x0001)
        proxy = Proxy(config)
        response = await proxy.call_method(0x0001, payload, timeout=5.0)
    """

    def __init__(self, config: ServiceInterfaceConfig):
        super().__init__(config)
        self._session_id = 0
        self._client_id = 0
        self._pending_requests: Dict[tuple, asyncio.Future] = {}
        self._timeout = 5.0  # Default request timeout

    @property
    def client_id(self) -> int:
        return self._client_id

    @client_id.setter
    def client_id(self, value: int) -> None:
        self._client_id = value

    def _next_session_id(self) -> int:
        """Get next session ID (wraps around at 0xFFFF)."""
        self._session_id = (self._session_id + 1) & 0xFFFF
        return self._session_id

    def build_request(
        self,
        method_id: int,
        payload: bytes = b"",
        fire_and_forget: bool = False,
    ) -> SomeipMessage:
        """Build a request message for a method."""
        session_id = self._next_session_id()
        return SomeipMessage.build_request(
            service_id=self.service_id,
            method_id=method_id,
            client_id=self._client_id,
            session_id=session_id,
            interface_version=self.interface_version,
            payload=payload,
            fire_and_forget=fire_and_forget,
        )

    async def call_method(
        self,
        method_id: int,
        payload: bytes = b"",
        timeout: Optional[float] = None,
    ) -> SomeipMessage:
        """Call a remote method and wait for the response.

        Returns the response message.
        Raises TimeoutError if the response is not received in time.
        """
        request = self.build_request(method_id, payload)
        return await self.send_and_wait(request, timeout=timeout)

    async def send_and_wait(
        self,
        request: SomeipMessage,
        timeout: Optional[float] = None,
    ) -> SomeipMessage:
        """Send a request and wait for the matching response.

        The request's client_id and session_id are used to correlate
        the response.
        """
        timeout = timeout or self._timeout
        request_key = (request.header.client_id, request.header.session_id)

        # Create a future for the response
        future = asyncio.get_running_loop().create_future()
        self._pending_requests[request_key] = future

        try:
            # The caller is responsible for actually sending the message
            # via the transport. We just manage the future here.
            # This method should be called by higher-level code that
            # also sends the request.

            # Wait for the response
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise SomeipTimeoutError(
                f"Request timed out: service=0x{self.service_id:04X} "
                f"method=0x{request.header.method_id:04X}"
            )
        finally:
            self._pending_requests.pop(request_key, None)

    def handle_response(self, message: SomeipMessage) -> bool:
        """Handle an incoming response message.

        Matches the response to a pending request and resolves the future.
        Returns True if the response was matched, False otherwise.
        """
        if message.header.message_type not in (
            MessageType.RESPONSE, MessageType.ERROR
        ):
            return False

        request_key = (message.header.client_id, message.header.session_id)
        future = self._pending_requests.get(request_key)

        if future and not future.done():
            future.set_result(message)
            return True

        return False

    def build_field_get(self, field_id: int) -> SomeipMessage:
        """Build a getter request for a field."""
        return self.build_request(field_id)

    def build_field_set(self, field_id: int, payload: bytes) -> SomeipMessage:
        """Build a setter request for a field."""
        return self.build_request(field_id + 1, payload)

    def build_notification_handler(
        self, event_id: int
    ) -> int:
        """Get the event ID with notification bit set for subscription."""
        return event_id | 0x8000
