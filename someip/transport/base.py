"""SOME/IP transport layer base class."""

from abc import ABC, abstractmethod
from typing import Callable, Optional, Union, Awaitable

from ..message.message import SomeipMessage


class AbstractTransport(ABC):
    """Abstract base class for SOME/IP transport implementations.

    Transports are responsible for sending and receiving raw SOME/IP
    messages over the network. They handle framing but NOT TP segmentation
    (that is handled by a higher layer).
    """

    def __init__(self):
        self._on_message: Optional[Callable[[SomeipMessage, tuple], Union[None, Awaitable]]] = None

    def set_message_handler(
        self, handler: Callable[[SomeipMessage, tuple], Union[None, Awaitable]]
    ) -> None:
        """Set the callback for received messages.

        The handler receives (message, source_address) where
        source_address is a (host, port) tuple.

        The handler may be a sync or async callable. If async,
        it will be scheduled as a task.
        """
        self._on_message = handler

    @abstractmethod
    async def start(self) -> None:
        """Start the transport (bind sockets, etc.)."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the transport (close sockets, cleanup)."""

    @abstractmethod
    async def send(self, message: SomeipMessage, endpoint: tuple) -> None:
        """Send a SOME/IP message to the given endpoint.

        Args:
            message: The SOME/IP message to send.
            endpoint: Destination (host, port) tuple.
        """

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the transport is currently active."""
