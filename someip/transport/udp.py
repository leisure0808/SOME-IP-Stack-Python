"""UDP transport for SOME/IP."""

import asyncio
import logging
from typing import Callable, Optional

from ..error import TransportError, MessageFormatError
from ..message.header import SOMEIP_HEADER_SIZE
from ..message.message import SomeipMessage
from .base import AbstractTransport

logger = logging.getLogger(__name__)


class UdpTransport(AbstractTransport):
    """SOME/IP transport over UDP.

    Uses asyncio DatagramProtocol for non-blocking I/O.
    Each UDP datagram carries exactly one SOME/IP message.
    """

    def __init__(self, local_port: int = 0, local_host: str = "0.0.0.0"):
        super().__init__()
        self._local_host = local_host
        self._local_port = local_port
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._protocol: Optional["_UdpProtocol"] = None
        self._endpoint: Optional[asyncio.AbstractServer] = None

    async def start(self) -> None:
        """Start listening for UDP datagrams."""
        loop = asyncio.get_running_loop()
        self._protocol = _UdpProtocol(self._on_message)

        try:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: self._protocol,
                local_addr=(self._local_host, self._local_port),
            )
            self._transport = transport
        except OSError as e:
            raise TransportError(f"Failed to bind UDP socket: {e}") from e

        # Get the actual bound port
        sock = self._transport.get_extra_info("socket")
        if sock:
            actual_addr = sock.getsockname()
            self._local_port = actual_addr[1]

        logger.info("UDP transport started on %s:%d", self._local_host, self._local_port)

    async def stop(self) -> None:
        """Stop the UDP transport."""
        if self._transport:
            self._transport.close()
            self._transport = None
        self._protocol = None
        logger.info("UDP transport stopped")

    async def send(self, message: SomeipMessage, endpoint: tuple) -> None:
        """Send a SOME/IP message via UDP datagram."""
        if not self._transport:
            raise TransportError("UDP transport not started")

        data = message.serialize()
        try:
            self._transport.sendto(data, endpoint)
        except OSError as e:
            raise TransportError(f"UDP send failed: {e}") from e

    @property
    def is_running(self) -> bool:
        return self._transport is not None

    @property
    def local_port(self) -> int:
        """The actual bound local port."""
        return self._local_port


class _UdpProtocol(asyncio.DatagramProtocol):
    """asyncio DatagramProtocol for receiving SOME/IP messages."""

    def __init__(self, message_handler: Optional[Callable]):
        self._message_handler = message_handler
        self._transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport):
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple):
        if not self._message_handler:
            return

        if len(data) < SOMEIP_HEADER_SIZE:
            logger.warning("Received too-short datagram from %s (%d bytes)", addr, len(data))
            return

        try:
            message = SomeipMessage.deserialize(data)
        except MessageFormatError as e:
            logger.warning("Failed to parse SOME/IP message from %s: %s", addr, e)
            return

        self._schedule_handler(self._message_handler, message, addr)

    @staticmethod
    def _schedule_handler(handler, message, addr):
        """Schedule handler, supporting both sync and async callables."""
        import asyncio
        import inspect
        result = handler(message, addr)
        if inspect.iscoroutine(result):
            asyncio.ensure_future(result)

    def error_received(self, exc: Exception):
        logger.error("UDP error: %s", exc)

    def connection_lost(self, exc: Optional[Exception]):
        if exc:
            logger.error("UDP connection lost: %s", exc)
