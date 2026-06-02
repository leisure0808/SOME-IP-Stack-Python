"""TCP transport for SOME/IP."""

import asyncio
import logging
from typing import Callable, Optional

from ..error import TransportError, MessageFormatError
from ..message.header import SOMEIP_HEADER_SIZE, SomeipHeader
from ..message.message import SomeipMessage
from .base import AbstractTransport

logger = logging.getLogger(__name__)


class TcpTransport(AbstractTransport):
    """SOME/IP transport over TCP.

    Uses asyncio StreamReader/StreamWriter for non-blocking I/O.
    TCP is stream-oriented, so we use the SOME/IP length field
    to detect message boundaries (frame-based protocol).
    """

    def __init__(self):
        super().__init__()
        self._server: Optional[asyncio.AbstractServer] = None
        self._connections: dict[tuple, asyncio.Task] = {}  # addr -> reader task
        self._writers: dict[tuple, asyncio.StreamWriter] = {}
        self._running = False
        self._listen_host = "0.0.0.0"
        self._listen_port = 0

    async def start(self, listen_host: str = "0.0.0.0", listen_port: int = 0) -> None:
        """Start TCP server listening for connections."""
        self._listen_host = listen_host
        self._listen_port = listen_port
        self._running = True

        try:
            self._server = await asyncio.start_server(
                self._handle_connection,
                listen_host,
                listen_port,
            )
            # Get actual bound port
            for sock in self._server.sockets:
                actual_addr = sock.getsockname()
                self._listen_port = actual_addr[1]
                break
        except OSError as e:
            raise TransportError(f"Failed to start TCP server: {e}") from e

        logger.info("TCP transport listening on %s:%d", listen_host, self._listen_port)

    async def connect(self, host: str, port: int) -> None:
        """Actively connect to a remote TCP endpoint."""
        try:
            reader, writer = await asyncio.open_connection(host, port)
            addr = writer.get_extra_info("peername")
            self._writers[addr] = writer
            task = asyncio.create_task(
                self._reader_loop(reader, addr), name=f"tcp-reader-{addr}"
            )
            self._connections[addr] = task
            logger.info("TCP connected to %s:%d", host, port)
        except OSError as e:
            raise TransportError(f"TCP connect failed to {host}:{port}: {e}") from e

    async def stop(self) -> None:
        """Stop the TCP transport and close all connections."""
        self._running = False

        # Close all writer connections
        for addr, writer in list(self._writers.items()):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self._writers.clear()

        # Cancel reader tasks
        for addr, task in list(self._connections.items()):
            task.cancel()
        for task in list(self._connections.values()):
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._connections.clear()

        # Close server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        logger.info("TCP transport stopped")

    async def send(self, message: SomeipMessage, endpoint: tuple) -> None:
        """Send a SOME/IP message to the given endpoint.

        If not already connected, attempts to connect first.
        """
        # endpoint is (host, port) -- find or create a writer
        writer = self._writers.get(endpoint)
        if writer is None:
            # Try connecting
            await self.connect(endpoint[0], endpoint[1])
            writer = self._writers.get(endpoint)
            if writer is None:
                raise TransportError(f"No TCP connection to {endpoint}")

        data = message.serialize()
        try:
            writer.write(data)
            await writer.drain()
        except OSError as e:
            raise TransportError(f"TCP send failed: {e}") from e

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def listen_port(self) -> int:
        return self._listen_port

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a new incoming TCP connection."""
        addr = writer.get_extra_info("peername")
        self._writers[addr] = writer
        logger.info("TCP connection from %s", addr)

        try:
            await self._reader_loop(reader, addr)
        except asyncio.CancelledError:
            pass
        finally:
            self._writers.pop(addr, None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _reader_loop(self, reader: asyncio.StreamReader, addr: tuple) -> None:
        """Read SOME/IP messages from a TCP stream.

        Uses the length field in the header to determine message boundaries.
        """
        while self._running:
            try:
                # Read the fixed-size header first (16 bytes)
                header_data = await reader.readexactly(SOMEIP_HEADER_SIZE)
            except asyncio.IncompleteReadError:
                logger.info("TCP connection closed by %s", addr)
                break
            except asyncio.CancelledError:
                break

            # Parse header to get the message length
            try:
                header, _ = SomeipHeader.deserialize(header_data)
            except MessageFormatError as e:
                logger.warning("Invalid SOME/IP header from %s: %s", addr, e)
                break

            # Total message size = 8 (service_id + method_id + length) + length
            remaining = header.length - 8  # remaining header bytes + payload
            payload_data = b""
            if remaining > 0:
                try:
                    payload_data = await reader.readexactly(remaining)
                except asyncio.IncompleteReadError:
                    logger.warning("Incomplete SOME/IP message from %s", addr)
                    break
                except asyncio.CancelledError:
                    break

            # Reconstruct full message and parse
            full_data = header_data + payload_data
            try:
                message = SomeipMessage.deserialize(full_data)
            except MessageFormatError as e:
                logger.warning("Failed to parse SOME/IP message from %s: %s", addr, e)
                continue

            if self._on_message:
                import inspect
                result = self._on_message(message, addr)
                if inspect.iscoroutine(result):
                    asyncio.ensure_future(result)
