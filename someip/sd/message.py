"""SOME/IP Service Discovery complete message."""

import struct
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..error import MessageFormatError
from ..message.header import SD_SERVICE_ID, SD_METHOD_ID, SomeipHeader
from ..message.message import SomeipMessage
from ..message.message_type import MessageType
from ..message.return_code import ReturnCode
from .entry import SdEntry, SD_ENTRY_SIZE
from .header import SdFlags
from .option import SdOption

logger = logging.getLogger(__name__)


@dataclass
class SdMessage:
    """Complete SOME/IP Service Discovery message.

    SD messages are regular SOME/IP messages with:
    - service_id = 0xFFFF
    - method_id = 0x8100
    - Payload: flags(4) + entries_length(4) + entries + options_length(4) + options
    """

    flags: SdFlags = field(default_factory=SdFlags)
    entries: List[SdEntry] = field(default_factory=list)
    options: List[SdOption] = field(default_factory=list)

    def serialize(self) -> bytes:
        """Serialize to a complete SOME/IP message."""
        # Encode entries
        entries_data = b""
        for entry in self.entries:
            entries_data += entry.serialize()

        # Encode options
        options_data = b""
        for option in self.options:
            options_data += option.serialize()

        # Build SD payload
        payload = bytearray()
        payload.extend(self.flags.serialize())
        payload.extend(struct.pack(">I", len(entries_data)))
        payload.extend(entries_data)
        payload.extend(struct.pack(">I", len(options_data)))
        payload.extend(options_data)

        # Build SOME/IP header
        length = 8 + len(payload)  # remaining header (8) + SD payload
        header = SomeipHeader(
            service_id=SD_SERVICE_ID,
            method_id=SD_METHOD_ID,
            length=length,
            client_id=0x0000,
            session_id=0x0000,  # TODO: session handling
            protocol_version=0x01,
            interface_version=0x01,
            message_type=MessageType.NOTIFICATION,
            return_code=ReturnCode.E_OK,
        )

        message = SomeipMessage(header=header, payload=bytes(payload))
        return message.serialize()

    @classmethod
    def deserialize_from_message(cls, message: SomeipMessage) -> "SdMessage":
        """Deserialize an SdMessage from a SomeipMessage.

        Raises MessageFormatError if the message is not a valid SD message.
        """
        if not message.header.is_sd:
            raise MessageFormatError("Not a Service Discovery message")

        data = message.payload
        offset = 0

        # Flags (4 bytes)
        if len(data) < 4:
            raise MessageFormatError("SD payload too short for flags")
        flags = SdFlags.deserialize(data, offset)
        offset += 4

        # Entries length + entries
        if len(data) < offset + 4:
            raise MessageFormatError("SD payload too short for entries length")
        entries_length = struct.unpack_from(">I", data, offset)[0]
        offset += 4

        entries = []
        entries_end = offset + entries_length
        while offset < entries_end:
            entry, consumed = SdEntry.deserialize(data, offset)
            entries.append(entry)
            offset += consumed

        # Options length + options
        if len(data) < offset + 4:
            raise MessageFormatError("SD payload too short for options length")
        options_length = struct.unpack_from(">I", data, offset)[0]
        offset += 4

        options = []
        options_end = offset + options_length
        while offset < options_end:
            option, consumed = SdOption.deserialize(data, offset)
            options.append(option)
            offset += consumed

        return cls(flags=flags, entries=entries, options=options)

    @classmethod
    def deserialize(cls, data: bytes) -> "SdMessage":
        """Deserialize from raw bytes (complete SOME/IP message)."""
        message = SomeipMessage.deserialize(data)
        return cls.deserialize_from_message(message)
