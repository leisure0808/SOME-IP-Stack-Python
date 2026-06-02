"""SOME/IP protocol stack implementation.

A complete SOME/IP (Scalable service-Oriented MiddlewarE over IP) protocol
stack in Python, supporting Windows and Linux, compatible with SOME/IP
specification versions 1.0 through 1.8.0.
"""

__version__ = "0.1.0"

from .error import (
    SomeipError,
    TransportError,
    SerializationError,
    MessageFormatError,
    SdError,
    ServiceUnavailableError,
    MethodNotFoundError,
    TimeoutError,
    TpReassemblyError,
    VersionMismatchError,
)
from .config import (
    ProtocolVersion,
    ServiceInterfaceConfig,
    StackConfiguration,
)
from .types import Codec, TypeRegistry
from .message import SomeipMessage, SomeipHeader, MessageType, ReturnCode
from .transport import UdpTransport, TcpTransport
from .service import Skeleton, Proxy, Dispatcher
from .sd import SdAgent, SdMessage

__all__ = [
    "__version__",
    # Errors
    "SomeipError", "TransportError", "SerializationError",
    "MessageFormatError", "SdError", "ServiceUnavailableError",
    "MethodNotFoundError", "TimeoutError", "TpReassemblyError",
    "VersionMismatchError",
    # Config
    "ProtocolVersion", "ServiceInterfaceConfig", "StackConfiguration",
    # Types
    "Codec", "TypeRegistry",
    # Message
    "SomeipMessage", "SomeipHeader", "MessageType", "ReturnCode",
    # Transport
    "UdpTransport", "TcpTransport",
    # Service
    "Skeleton", "Proxy", "Dispatcher",
    # SD
    "SdAgent", "SdMessage",
]
