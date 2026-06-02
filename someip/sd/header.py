"""SOME/IP Service Discovery header."""

import struct
from dataclasses import dataclass
from typing import Tuple

from ..error import MessageFormatError

# SD header size: flags(1) + reserved(3) + length_entries_array(4) = 8 bytes after SOME/IP header
SD_HEADER_SIZE = 12  # After SOME/IP header: flags(4) + entries_length(4) + options_length(4) wait
# Actually the SD specific part starts after the SOME/IP header:
# - Flags (4 bytes): reboot_flag(1bit) + unicast_flag(1bit) + reserved(30bits)
# - Length of Entries Array (4 bytes)
# - Entries Array (variable)
# - Length of Options Array (4 bytes)
# - Options Array (variable)

# The flags + entries_length is 8 bytes before entries
SD_FLAGS_AND_ENTRIES_LENGTH_SIZE = 8


@dataclass
class SdFlags:
    """SD flags field (4 bytes)."""

    reboot_flag: bool = False
    unicast_flag: bool = False
    explicit_initial_data_control: bool = False

    def serialize(self) -> bytes:
        flags_byte = 0
        if self.reboot_flag:
            flags_byte |= 0x80
        if self.unicast_flag:
            flags_byte |= 0x40
        if self.explicit_initial_data_control:
            flags_byte |= 0x20
        return struct.pack(">I", flags_byte << 24)  # flags in MSByte

    @classmethod
    def deserialize(cls, data: bytes, offset: int = 0) -> "SdFlags":
        raw = struct.unpack_from(">I", data, offset)[0]
        return cls(
            reboot_flag=bool(raw & 0x80000000),
            unicast_flag=bool(raw & 0x40000000),
            explicit_initial_data_control=bool(raw & 0x20000000),
        )
