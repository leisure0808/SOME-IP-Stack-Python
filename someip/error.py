"""SOME/IP protocol stack exception hierarchy."""


class SomeipError(Exception):
    """Base exception for all SOME/IP stack errors."""


class TransportError(SomeipError):
    """Transport layer errors (connection refused, socket errors)."""


class SerializationError(SomeipError):
    """Errors during encode/decode (type mismatch, buffer overrun, alignment)."""


class MessageFormatError(SomeipError):
    """Malformed SOME/IP message (wrong length, invalid field values)."""


class SdError(SomeipError):
    """Service Discovery errors."""


class ServiceUnavailableError(SomeipError):
    """Requested service not found / not offered."""


class MethodNotFoundError(SomeipError):
    """Requested method not found in service."""


class TimeoutError(SomeipError):
    """Request timed out waiting for response."""


class TpReassemblyError(SomeipError):
    """TP segment reassembly failure (timeout, duplicate, out-of-order)."""


class VersionMismatchError(SomeipError):
    """Protocol or interface version mismatch."""
