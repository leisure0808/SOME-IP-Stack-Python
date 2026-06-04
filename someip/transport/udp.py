"""UDP transport for SOME/IP."""

import asyncio
import ctypes
import logging
import socket
import struct
import sys
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

        # On Windows, create the socket manually so we can disable
        # WSAECONNRESET before handing it to asyncio. This prevents ICMP
        # Port Unreachable errors from breaking the receive loop.
        if sys.platform == "win32":
            import socket as _socket
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            self._disable_wsaconnreset(sock)
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
            sock.bind((self._local_host, self._local_port))
            sock.setblocking(False)

            try:
                transport, protocol = await loop.create_datagram_endpoint(
                    lambda: self._protocol,
                    sock=sock,
                )
                self._transport = transport
            except OSError as e:
                sock.close()
                raise TransportError(f"Failed to bind UDP socket: {e}") from e
        else:
            try:
                transport, protocol = await loop.create_datagram_endpoint(
                    lambda: self._protocol,
                    local_addr=(self._local_host, self._local_port),
                )
                self._transport = transport
            except OSError as e:
                raise TransportError(f"Failed to bind UDP socket: {e}") from e

        # Get the actual bound port
        sock_info = self._transport.get_extra_info("socket")
        if sock_info:
            actual_addr = sock_info.getsockname()
            self._local_port = actual_addr[1]

        logger.info("UDP transport started on %s:%d", self._local_host, self._local_port)

    def set_message_handler(self, handler) -> None:
        """Set the callback for received messages.

        The handler receives (message, source_address) where
        source_address is a (host, port) tuple. May be called
        before or after start().
        """
        self._on_message = handler
        # If protocol is already running, update its handler too
        if self._protocol is not None:
            self._protocol._message_handler = handler

    @staticmethod
    def _disable_wsaconnreset(sock) -> None:
        """Disable WSAECONNRESET on a Windows UDP socket.

        On Windows, when a UDP socket sends to an unreachable port and receives
        an ICMP Port Unreachable response, the socket enters a state where
        subsequent recvfrom() calls fail with WSAECONNRESET, blocking new
        incoming datagrams. Setting SIO_UDP_CONNRESET to FALSE prevents this.
        """
        try:
            from ctypes import windll, wintypes, byref

            SIO_UDP_CONNRESET = 0x9800000C
            input_buf = wintypes.BOOL(False)
            bytes_returned = wintypes.DWORD()

            result = windll.ws2_32.WSAIoctl(
                sock.fileno(),
                SIO_UDP_CONNRESET,
                byref(input_buf),
                ctypes.sizeof(input_buf),
                None,
                0,
                byref(bytes_returned),
                None,
                None,
            )
            if result == 0:
                logger.debug("Disabled WSAECONNRESET on UDP socket")
            else:
                error = windll.ws2_32.WSAGetLastError()
                logger.warning("WSAIoctl SIO_UDP_CONNRESET failed: error %d", error)
        except Exception as e:
            logger.warning("Failed to disable WSAECONNRESET: %s", e)

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

    def join_multicast_group(self, multicast_addr: str, interface: str = "0.0.0.0") -> None:
        """Join a multicast group on this socket.

        Must be called after start(). Enables receiving multicast datagrams
        sent to the specified group address.

        Args:
            multicast_addr: Multicast group address (e.g. "224.224.224.245").
            interface: Network interface address for the group membership.
                       Use "127.0.0.1" for localhost testing.

        Raises TransportError if the socket is not available. Logs a warning
        and returns gracefully on OS-level errors (e.g. no multicast route),
        allowing unicast-only operation.
        """
        if not self._transport:
            raise TransportError("Transport not started")

        sock = self._transport.get_extra_info("socket")
        if sock is None:
            raise TransportError("Cannot access underlying socket")

        group = socket.inet_aton(multicast_addr)
        iface = socket.inet_aton(interface)

        try:
            # Join the multicast group
            mreq = group + iface
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            # Set outgoing interface for multicast sends
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, iface)

            # Enable loopback so local sends are received (needed for localhost testing)
            sock.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, struct.pack("b", 1)
            )

            logger.info(
                "Joined multicast group %s on interface %s", multicast_addr, interface
            )
        except OSError as e:
            logger.warning(
                "Failed to join multicast group %s (multicast may not work): %s",
                multicast_addr, e,
            )

    def leave_multicast_group(self, multicast_addr: str, interface: str = "0.0.0.0") -> None:
        """Leave a multicast group.

        Safe to call even if the group was never joined.
        """
        if not self._transport:
            return

        sock = self._transport.get_extra_info("socket")
        if sock is None:
            return

        group = socket.inet_aton(multicast_addr)
        iface = socket.inet_aton(interface)
        mreq = group + iface

        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
            logger.info("Left multicast group %s", multicast_addr)
        except OSError as e:
            logger.debug("Failed to leave multicast group %s: %s", multicast_addr, e)


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
