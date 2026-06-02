"""SOME/IP return code definitions."""

from enum import IntEnum


class ReturnCode(IntEnum):
    """SOME/IP return code field values.

    Return codes indicate the result of processing a request message.
    """

    E_OK = 0x00
    E_NOT_OK = 0x01
    E_UNKNOWN_SERVICE = 0x02
    E_UNKNOWN_METHOD = 0x03
    E_NOT_READY = 0x04
    E_NOT_REACHABLE = 0x05
    E_TIMEOUT = 0x06
    E_WRONG_PROTOCOL_VERSION = 0x07
    E_WRONG_INTERFACE_VERSION = 0x08
    E_MALFORMED_MESSAGE = 0x09
    E_WRONG_MESSAGE_TYPE = 0x0A

    # v1.6+ additions
    E_E2E_REPEATED = 0x0B
    E_E2E_WRONG_SEQUENCE = 0x0C
    E_E2E = 0x0D
    E_E2E_NOT_AVAILABLE = 0x0E

    # v1.8.0 additions
    E_UNKNOWN_EVENTGROUP = 0x0F

    def is_error(self) -> bool:
        """Check if this return code indicates an error."""
        return self != ReturnCode.E_OK
