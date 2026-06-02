"""SOME/IP complete message (header + payload)."""

from dataclasses import dataclass
from typing import Optional

from ..error import MessageFormatError
from .header import SOMEIP_HEADER_SIZE, SomeipHeader
from .message_type import MessageType
from .return_code import ReturnCode


@dataclass
class SomeipMessage:
    """Complete SOME/IP message consisting of a header and payload.

    The header contains the message metadata (service ID, method ID, etc.)
    and the payload is the raw bytes of the serialized data.
    """

    header: SomeipHeader
    payload: bytes

    def serialize(self) -> bytes:
        """Serialize the complete SOME/IP message to bytes."""
        return self.header.serialize() + self.payload

    @classmethod
    def deserialize(cls, data: bytes) -> "SomeipMessage":
        """Deserialize a complete SOME/IP message from bytes.

        The header's length field determines how many bytes to read for
        the full message.
        """
        if len(data) < SOMEIP_HEADER_SIZE:
            raise MessageFormatError(
                f"Data too short for SOME/IP message: {len(data)} bytes"
            )

        header, header_size = SomeipHeader.deserialize(data)

        # Length field = bytes after service_id + method_id + length field itself
        # i.e., length includes the remaining 8 bytes of header + payload
        total_message_size = 8 + header.length  # 8 = service_id(2) + method_id(2) + length(4)

        if len(data) < total_message_size:
            raise MessageFormatError(
                f"Incomplete message: have {len(data)} bytes, need {total_message_size}"
            )

        payload = data[SOMEIP_HEADER_SIZE:total_message_size]
        return cls(header=header, payload=payload)

    @classmethod
    def build_request(
        cls,
        service_id: int,
        method_id: int,
        client_id: int,
        session_id: int,
        interface_version: int,
        payload: bytes,
        fire_and_forget: bool = False,
        protocol_version: int = 0x01,
    ) -> "SomeipMessage":
        """Build a request message.

        Args:
            service_id: Service identifier.
            method_id: Method identifier.
            client_id: Client identifier.
            session_id: Session identifier.
            interface_version: Interface version.
            payload: Serialized request payload.
            fire_and_forget: If True, use REQUEST_NO_RETURN type.
            protocol_version: Protocol version (default 0x01).
        """
        msg_type = (
            MessageType.REQUEST_NO_RETURN
            if fire_and_forget
            else MessageType.REQUEST
        )
        length = 8 + len(payload)  # remaining header (8) + payload

        header = SomeipHeader(
            service_id=service_id,
            method_id=method_id,
            length=length,
            client_id=client_id,
            session_id=session_id,
            protocol_version=protocol_version,
            interface_version=interface_version,
            message_type=msg_type,
            return_code=ReturnCode.E_OK,
        )
        return cls(header=header, payload=payload)

    @classmethod
    def build_response(
        cls,
        request: "SomeipMessage",
        interface_version: int,
        payload: bytes,
        return_code: ReturnCode = ReturnCode.E_OK,
        protocol_version: int = 0x01,
    ) -> "SomeipMessage":
        """Build a response message for a given request.

        Copies service_id, method_id, client_id, session_id from the request.
        """
        length = 8 + len(payload)

        header = SomeipHeader(
            service_id=request.header.service_id,
            method_id=request.header.method_id,
            length=length,
            client_id=request.header.client_id,
            session_id=request.header.session_id,
            protocol_version=protocol_version,
            interface_version=interface_version,
            message_type=MessageType.RESPONSE,
            return_code=return_code,
        )
        return cls(header=header, payload=payload)

    @classmethod
    def build_error(
        cls,
        request: "SomeipMessage",
        interface_version: int,
        return_code: ReturnCode,
        payload: bytes = b"",
        protocol_version: int = 0x01,
    ) -> "SomeipMessage":
        """Build an error response message.

        Similar to build_response but with ERROR message type.
        """
        length = 8 + len(payload)

        header = SomeipHeader(
            service_id=request.header.service_id,
            method_id=request.header.method_id,
            length=length,
            client_id=request.header.client_id,
            session_id=request.header.session_id,
            protocol_version=protocol_version,
            interface_version=interface_version,
            message_type=MessageType.ERROR,
            return_code=return_code,
        )
        return cls(header=header, payload=payload)

    @classmethod
    def build_notification(
        cls,
        service_id: int,
        event_id: int,
        client_id: int,
        session_id: int,
        interface_version: int,
        payload: bytes,
        protocol_version: int = 0x01,
    ) -> "SomeipMessage":
        """Build a notification/event message.

        The method_id has bit 15 (0x8000) set to indicate notification.
        """
        method_id = event_id | 0x8000
        length = 8 + len(payload)

        header = SomeipHeader(
            service_id=service_id,
            method_id=method_id,
            length=length,
            client_id=client_id,
            session_id=session_id,
            protocol_version=protocol_version,
            interface_version=interface_version,
            message_type=MessageType.NOTIFICATION,
            return_code=ReturnCode.E_OK,
        )
        return cls(header=header, payload=payload)

    @property
    def total_length(self) -> int:
        """Total message length in bytes (header + payload)."""
        return SOMEIP_HEADER_SIZE + len(self.payload)
