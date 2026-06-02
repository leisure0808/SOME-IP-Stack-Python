"""SOME/IP message header serialization."""

import struct
from dataclasses import dataclass
from typing import Tuple

from ..error import MessageFormatError
from .message_type import MessageType
from .return_code import ReturnCode

# SOME/IP header is always 16 bytes
SOMEIP_HEADER_SIZE = 16

# SD messages use fixed service_id and method_id
SD_SERVICE_ID = 0xFFFF
SD_METHOD_ID = 0x8100


@dataclass
class SomeipHeader:
    """SOME/IP message header (16 bytes).

    Layout (big-endian):
        Offset  Size  Field
        0       2     Service ID
        2       2     Method ID
        4       4     Length (bytes after this field, including remaining header)
        8       2     Client ID
        10      2     Session ID
        12      1     Protocol Version (0x01)
        13      1     Interface Version
        14      1     Message Type
        15      1     Return Code
    """

    service_id: int
    method_id: int
    length: int
    client_id: int
    session_id: int
    protocol_version: int
    interface_version: int
    message_type: MessageType
    return_code: ReturnCode

    @property
    def message_id(self) -> int:
        """Combined message ID (service_id | method_id)."""
        return (self.service_id << 16) | self.method_id

    @property
    def request_id(self) -> int:
        """Combined request ID (client_id | session_id)."""
        return (self.client_id << 16) | self.session_id

    @property
    def is_sd(self) -> bool:
        """Whether this is a Service Discovery message."""
        return self.service_id == SD_SERVICE_ID and self.method_id == SD_METHOD_ID

    @property
    def is_notification(self) -> bool:
        """Whether this is a notification (method_id bit 15 set)."""
        return bool(self.method_id & 0x8000)

    @property
    def is_tp(self) -> bool:
        """Whether this message has the TP flag set."""
        return self.message_type.is_tp()

    def serialize(self) -> bytes:
        """Serialize header to 16-byte big-endian binary."""
        return struct.pack(
            ">HHIHHBBBB",
            self.service_id,
            self.method_id,
            self.length,
            self.client_id,
            self.session_id,
            self.protocol_version,
            self.interface_version,
            int(self.message_type),
            int(self.return_code),
        )

    @classmethod
    def deserialize(cls, data: bytes) -> Tuple["SomeipHeader", int]:
        """Deserialize header from bytes.

        Returns (header, bytes_consumed).
        Raises MessageFormatError if data is too short.
        """
        if len(data) < SOMEIP_HEADER_SIZE:
            raise MessageFormatError(
                f"Header too short: {len(data)} bytes, need {SOMEIP_HEADER_SIZE}"
            )

        service_id, method_id, length, client_id, session_id, \
            proto_ver, iface_ver, msg_type_raw, ret_code_raw = struct.unpack(
                ">HHIHHBBBB", data[:SOMEIP_HEADER_SIZE]
            )

        try:
            msg_type = MessageType(msg_type_raw)
        except ValueError:
            msg_type = MessageType(msg_type_raw)  # Keep raw value

        try:
            ret_code = ReturnCode(ret_code_raw)
        except ValueError:
            ret_code = ReturnCode(ret_code_raw)  # Keep raw value

        header = cls(
            service_id=service_id,
            method_id=method_id,
            length=length,
            client_id=client_id,
            session_id=session_id,
            protocol_version=proto_ver,
            interface_version=iface_ver,
            message_type=msg_type,
            return_code=ret_code,
        )
        return header, SOMEIP_HEADER_SIZE
