"""SOME/IP message type definitions.

Per AUTOSAR SOME/IP specification:
- Bit 7 (0x80): Response indicator (0 = request/notification, 1 = response/error)
- Bit 5 (0x20): TP flag (1 = segmented message via SOME/IP-TP)
- Bit 6 (0x40): Ack flag (optional, v1.5+)

Base message types:
    REQUEST             = 0x00
    REQUEST_NO_RETURN   = 0x01
    NOTIFICATION        = 0x02

TP segmented variants (bit 5 = TP flag):
    TP_REQUEST          = 0x20
    TP_REQUEST_NO_RETURN = 0x21
    TP_NOTIFICATION     = 0x22

Ack variants (bit 6 = Ack flag):
    REQUEST_ACK             = 0x40
    REQUEST_NO_RETURN_ACK   = 0x41
    NOTIFICATION_ACK        = 0x42

Response types (bit 7 = 1):
    RESPONSE    = 0x80
    ERROR       = 0x81

TP response variants (bits 7+5):
    TP_RESPONSE = 0xA0
    TP_ERROR    = 0xA1
"""

from enum import IntEnum

# TP flag mask: bit 5 per AUTOSAR spec
_TP_FLAG_MASK = 0x20


class MessageType(IntEnum):
    """SOME/IP message type field values per AUTOSAR specification."""

    # Request types
    REQUEST = 0x00
    REQUEST_NO_RETURN = 0x01  # Fire & Forget
    NOTIFICATION = 0x02

    # TP segmented variants (bit 5 = TP flag)
    TP_REQUEST = 0x20
    TP_REQUEST_NO_RETURN = 0x21
    TP_NOTIFICATION = 0x22

    # Ack types (bit 6 = Ack flag)
    REQUEST_ACK = 0x40
    REQUEST_NO_RETURN_ACK = 0x41
    NOTIFICATION_ACK = 0x42

    # Response types (bit 7 = 1)
    RESPONSE = 0x80
    ERROR = 0x81

    # TP response variants (bits 7+5)
    TP_RESPONSE = 0xA0
    TP_ERROR = 0xA1

    def is_request_type(self) -> bool:
        """Check if this is a request-type message (expects a response)."""
        return self in (MessageType.REQUEST, MessageType.REQUEST_ACK)

    def is_fire_and_forget(self) -> bool:
        """Check if this is a fire-and-forget request."""
        return self in (MessageType.REQUEST_NO_RETURN,
                        MessageType.REQUEST_NO_RETURN_ACK)

    def is_notification(self) -> bool:
        """Check if this is a notification/event message."""
        return self in (MessageType.NOTIFICATION, MessageType.NOTIFICATION_ACK)

    def is_response_type(self) -> bool:
        """Check if this is a response or error message."""
        return self in (MessageType.RESPONSE, MessageType.ERROR)

    def is_tp(self) -> bool:
        """Check if this message type has the TP flag set (bit 5)."""
        return bool(self & _TP_FLAG_MASK)

    def is_ack(self) -> bool:
        """Check if this message type has the Ack flag set (bit 6)."""
        return bool(self & 0x40)

    def with_tp(self) -> "MessageType":
        """Return the TP variant of this message type (set bit 5)."""
        tp_val = int(self) | _TP_FLAG_MASK
        try:
            return MessageType(tp_val)
        except ValueError:
            return MessageType(tp_val)

    def without_tp(self) -> "MessageType":
        """Return the non-TP variant of this message type (clear bit 5)."""
        base_val = int(self) & ~_TP_FLAG_MASK
        try:
            return MessageType(base_val)
        except ValueError:
            return MessageType(base_val)

    @classmethod
    def set_tp_flag(cls, msg_type: int) -> int:
        """Set the TP flag on a message type value."""
        return msg_type | _TP_FLAG_MASK

    @classmethod
    def clear_tp_flag(cls, msg_type: int) -> int:
        """Clear the TP flag from a message type value."""
        return msg_type & ~_TP_FLAG_MASK
