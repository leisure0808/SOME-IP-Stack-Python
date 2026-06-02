"""SOME/IP Service Discovery entry types.

SD entry layout (16 bytes):
    Byte 0:    Type (uint8)
    Byte 1:    Index 1st Options (upper 4 bits) | Index 2nd Options (lower 4 bits)
    Byte 2:    # of Option 1 (upper 4 bits) | # of Option 2 (lower 4 bits)
    Byte 3-4:  Service ID (uint16)
    Byte 5-6:  Instance ID (uint16)
    Byte 7:    Major Version (uint8)
    Byte 8-10: TTL (3 bytes, uint24)
    Byte 11-15: depends on entry type:
        Service entry: Minor Version (uint32 + 1 reserved byte = 4 bytes)
            Actually: 4 bytes = Minor Version (uint32)
        EventGroup entry: Reserved (uint8) + EventGroup ID (uint16) + Reserved (uint8)
"""

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Tuple

from ..error import MessageFormatError


class SdEntryType(IntEnum):
    """SD entry type field values."""

    FIND_SERVICE = 0x00
    OFFER_SERVICE = 0x01
    SUBSCRIBE_EVENTGROUP = 0x06
    SUBSCRIBE_EVENTGROUP_ACK = 0x07
    SUBSCRIBE_EVENTGROUP_NACK = 0x08


SD_ENTRY_SIZE = 16


@dataclass
class SdEntry:
    """SOME/IP SD entry (16 bytes)."""

    entry_type: SdEntryType
    service_id: int
    instance_id: int
    major_version: int
    ttl: int
    # Service entries
    minor_version: int = 0
    # EventGroup entries
    eventgroup_id: int = 0
    # Option indices and counts
    index_option_1: int = 0
    index_option_2: int = 0
    num_options_1: int = 0
    num_options_2: int = 0

    @property
    def is_service_entry(self) -> bool:
        return self.entry_type in (
            SdEntryType.FIND_SERVICE,
            SdEntryType.OFFER_SERVICE,
        )

    @property
    def is_eventgroup_entry(self) -> bool:
        return self.entry_type in (
            SdEntryType.SUBSCRIBE_EVENTGROUP,
            SdEntryType.SUBSCRIBE_EVENTGROUP_ACK,
            SdEntryType.SUBSCRIBE_EVENTGROUP_NACK,
        )

    @property
    def is_stop(self) -> bool:
        return self.ttl == 0

    def serialize(self) -> bytes:
        """Serialize to 16-byte SD entry."""
        type_byte = int(self.entry_type)

        # Byte 1: index options
        opt_index = ((self.index_option_1 & 0x0F) << 4) | (self.index_option_2 & 0x0F)

        # Byte 2: number of options
        opt_count = ((self.num_options_1 & 0x0F) << 4) | (self.num_options_2 & 0x0F)

        # TTL is 3 bytes (24 bits)
        ttl_b1 = (self.ttl >> 16) & 0xFF
        ttl_b2 = (self.ttl >> 8) & 0xFF
        ttl_b3 = self.ttl & 0xFF

        if self.is_eventgroup_entry:
            # Last 4 bytes: reserved(1) + eventgroup_id(2) + reserved(1)
            return struct.pack(
                ">BBBBHHBBBB B H B",
                type_byte,
                opt_index,
                opt_count,
                0,  # reserved
                self.service_id,
                self.instance_id,
                self.major_version,
                ttl_b1, ttl_b2, ttl_b3,
                0,  # reserved
                self.eventgroup_id,
                0,  # reserved
            )
        else:
            # Last 4 bytes: minor_version (uint32)
            return struct.pack(
                ">BBBBHHBBBB I",
                type_byte,
                opt_index,
                opt_count,
                0,  # reserved
                self.service_id,
                self.instance_id,
                self.major_version,
                ttl_b1, ttl_b2, ttl_b3,
                self.minor_version,
            )

    @classmethod
    def deserialize(cls, data: bytes, offset: int = 0) -> Tuple["SdEntry", int]:
        """Deserialize SD entry from bytes.

        Returns (entry, bytes_consumed).
        """
        if len(data) < offset + SD_ENTRY_SIZE:
            raise MessageFormatError(
                f"SD entry too short: {len(data) - offset} bytes, need {SD_ENTRY_SIZE}"
            )

        # Unpack the first 12 bytes
        type_raw = data[offset]
        opt_index_raw = data[offset + 1]
        opt_count_raw = data[offset + 2]

        service_id, instance_id = struct.unpack_from(">HH", data, offset + 4)
        major_version = data[offset + 8]
        ttl = (data[offset + 9] << 16) | (data[offset + 10] << 8) | data[offset + 11]

        try:
            entry_type = SdEntryType(type_raw)
        except ValueError:
            entry_type = SdEntryType(type_raw)

        index_option_1 = (opt_index_raw >> 4) & 0x0F
        index_option_2 = opt_index_raw & 0x0F
        num_options_1 = (opt_count_raw >> 4) & 0x0F
        num_options_2 = opt_count_raw & 0x0F

        entry = cls(
            entry_type=entry_type,
            service_id=service_id,
            instance_id=instance_id,
            major_version=major_version,
            ttl=ttl,
            index_option_1=index_option_1,
            index_option_2=index_option_2,
            num_options_1=num_options_1,
            num_options_2=num_options_2,
        )

        # Parse last 4 bytes based on type
        if entry.is_eventgroup_entry:
            # reserved(1) + eventgroup_id(2) + reserved(1)
            eventgroup_id = struct.unpack_from(">H", data, offset + 13)[0]
            entry.eventgroup_id = eventgroup_id
        else:
            # minor_version (uint32)
            minor_version = struct.unpack_from(">I", data, offset + 12)[0]
            entry.minor_version = minor_version

        return entry, SD_ENTRY_SIZE
