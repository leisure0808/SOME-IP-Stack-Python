"""SOME/IP message type definitions."""

from enum import IntEnum


class MessageType(IntEnum):
    """SOME/IP message type field values.

    The message type indicates whether the message is a request,
    response, notification, or error. TP (Transport Protocol) variants
    have bit 4 set (0x10).
    """

    REQUEST = 0x00
    REQUEST_NO_RETURN = 0x01  # Fire & Forget
    NOTIFICATION = 0x02

    # TP segmented variants (bit 4 = TP flag, v1.5+)
    TP_REQUEST = 0x10
    TP_REQUEST_NO_RETURN = 0x11
    TP_NOTIFICATION = 0x12

    # TP ACK types (v1.5+)
    REQUEST_ACK = 0x40
    NOTIFICATION_ACK = 0x41

    RESPONSE = 0x80
    ERROR = 0x81

    # TP segmented response variants
    TP_RESPONSE = 0x90
    TP_ERROR = 0x91

    # TP ACK types for responses (v1.5+)
    RESPONSE_ACK = 0xC0
    ERROR_ACK = 0xC1

    def is_request_type(self) -> bool:
        """Check if this is a request-type message (expects a response)."""
        return self in (MessageType.REQUEST,)

    def is_fire_and_forget(self) -> bool:
        """Check if this is a fire-and-forget request."""
        return self == MessageType.REQUEST_NO_RETURN

    def is_notification(self) -> bool:
        """Check if this is a notification/event message."""
        return self in (MessageType.NOTIFICATION, MessageType.NOTIFICATION_ACK)

    def is_response_type(self) -> bool:
        """Check if this is a response or error message."""
        return self in (MessageType.RESPONSE, MessageType.ERROR,
                        MessageType.RESPONSE_ACK, MessageType.ERROR_ACK)

    def is_tp(self) -> bool:
        """Check if this message type has the TP flag set."""
        return bool(self & 0x10)

    def is_tp_ack(self) -> bool:
        """Check if this is a TP acknowledgement type."""
        return self in (MessageType.REQUEST_ACK, MessageType.NOTIFICATION_ACK,
                        MessageType.RESPONSE_ACK, MessageType.ERROR_ACK)

    def with_tp(self) -> "MessageType":
        """Return the TP variant of this message type (set bit 4)."""
        tp_val = int(self) | 0x10
        try:
            return MessageType(tp_val)
        except ValueError:
            return MessageType(tp_val)

    def without_tp(self) -> "MessageType":
        """Return the non-TP variant of this message type (clear bit 4)."""
        base_val = int(self) & ~0x10
        try:
            return MessageType(base_val)
        except ValueError:
            return MessageType(base_val)

    @classmethod
    def set_tp_flag(cls, msg_type: int) -> int:
        """Set the TP flag on a message type."""
        return msg_type | 0x10

    @classmethod
    def clear_tp_flag(cls, msg_type: int) -> int:
        """Clear the TP flag from a message type."""
        return msg_type & ~0x10
