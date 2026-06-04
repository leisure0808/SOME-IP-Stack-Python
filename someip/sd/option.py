"""SOME/IP Service Discovery option types.

All options share a common header:
    [uint16 length] [uint8 type] [uint8 reserved]

The length field counts bytes AFTER the length field itself:
    length = 1 (type) + 1 (reserved) + data_bytes

For IPv4 Endpoint: length = 9 (type=1 + reserved=1 + reserved=1 + proto=1 + port=2 + addr=4)
    Total option size = 2 (length) + 9 = 11 bytes... but per AUTOSAR spec it's padded to 12.
    Actually: length=0009h, total bytes = 2 + 9 = 11, but options are 4-byte aligned.
    So total_size = 12 with 1 byte padding.
    But length field itself is 9, meaning bytes_after_length = 9.
"""

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional, Tuple

from ..error import MessageFormatError


class SdOptionType(IntEnum):
    """SD option type field values."""

    CONFIGURATION = 0x01
    LOAD_BALANCING = 0x02
    IPv4_ENDPOINT = 0x04
    IPv6_ENDPOINT = 0x06
    IPv4_MULTICAST = 0x14
    IPv6_MULTICAST = 0x16
    IPv4_SD_ENDPOINT = 0x24
    IPv6_SD_ENDPOINT = 0x26


@dataclass
class SdOption:
    """Base class for SD options."""

    option_type: SdOptionType

    def serialize(self) -> bytes:
        raise NotImplementedError

    @staticmethod
    def deserialize(data: bytes, offset: int = 0) -> Tuple["SdOption", int]:
        """Deserialize an SD option from bytes.

        Returns (option, bytes_consumed).
        """
        if len(data) < offset + 4:
            raise MessageFormatError("SD option too short for header")

        length, opt_type_raw, reserved = struct.unpack_from(">HBB", data, offset)

        try:
            opt_type = SdOptionType(opt_type_raw)
        except ValueError:
            opt_type = SdOptionType(opt_type_raw)

        # Total option bytes = length field(2) + length_value
        # But length counts bytes after the length field:
        #   length = type(1) + reserved(1) + data
        # So total = 2 + length
        # But options are padded to 4-byte boundaries
        raw_total = 2 + length
        # Align to 4 bytes
        total_size = (raw_total + 3) & ~3

        if len(data) < offset + raw_total:
            raise MessageFormatError(
                f"SD option truncated: need {raw_total}, have {len(data) - offset}"
            )

        # Parse the option data (after type + reserved)
        option_data = data[offset + 4:offset + raw_total]

        if opt_type in (SdOptionType.IPv4_ENDPOINT, SdOptionType.IPv4_SD_ENDPOINT,
                        SdOptionType.IPv4_MULTICAST):
            return _deserialize_ipv4_option(opt_type, option_data, total_size)
        elif opt_type in (SdOptionType.IPv6_ENDPOINT, SdOptionType.IPv6_SD_ENDPOINT,
                          SdOptionType.IPv6_MULTICAST):
            return _deserialize_ipv6_option(opt_type, option_data, total_size)
        elif opt_type == SdOptionType.CONFIGURATION:
            return _deserialize_config_option(opt_type, option_data, total_size)
        else:
            option = SdOption(option_type=opt_type)
            return option, total_size


def _ip_to_bytes(address: str) -> bytes:
    parts = address.split(".")
    if len(parts) != 4:
        raise ValueError(f"Invalid IPv4 address: {address}")
    return bytes(int(p) & 0xFF for p in parts)


def _bytes_to_ip(data: bytes) -> str:
    return ".".join(str(b) for b in data[:4])


@dataclass
class IPv4EndpointOption:
    """IPv4 endpoint option (type 0x04, 0x24, 0x14).

    After common header (type + reserved):
        [uint8 reserved] [uint8 L4 Proto] [uint16 port] [4 bytes IPv4 addr]
    Total data after length field: 1+1+1+2+4 = 9 bytes
    Length field value = 9
    Total with header = 11, padded to 12
    """

    option_type: SdOptionType = SdOptionType.IPv4_ENDPOINT
    address: str = "0.0.0.0"
    port: int = 0
    protocol: int = 17  # 6=TCP, 17=UDP

    def serialize(self) -> bytes:
        addr_bytes = _ip_to_bytes(self.address)
        # Data after length field: type(1) + reserved(1) + reserved(1) + proto(1) + port(2) + addr(4)
        data = struct.pack(">BBH", 0, self.protocol, self.port) + addr_bytes
        # length = type(1) + reserved(1) + data = 2 + 7 = 9
        length = 2 + len(data)  # type + reserved + payload
        header = struct.pack(">HBB", length, int(self.option_type), 0)
        raw = header + data

        # Pad to 4-byte boundary
        pad = (4 - (len(raw) % 4)) % 4
        return raw + b"\x00" * pad


def _deserialize_ipv4_option(
    opt_type: SdOptionType, data: bytes, total_size: int
) -> Tuple[IPv4EndpointOption, int]:
    # data is after type(1) + reserved(1) = 7 bytes:
    # reserved(1) + proto(1) + port(2) + addr(4)
    if len(data) < 7:
        raise MessageFormatError("IPv4 option data too short")

    _, protocol, port = struct.unpack_from(">BBH", data, 0)
    address = _bytes_to_ip(data[4:8])

    option = IPv4EndpointOption(
        option_type=opt_type,
        address=address,
        port=port,
        protocol=protocol,
    )
    return option, total_size


@dataclass
class ConfigOption:
    """Configuration option (type 0x01).

    Key-value pairs separated by '=', entries separated by '\\0'.
    """

    option_type: SdOptionType = SdOptionType.CONFIGURATION
    configuration: Dict[str, str] = None

    def __post_init__(self):
        if self.configuration is None:
            self.configuration = {}

    def serialize(self) -> bytes:
        entries = []
        for k, v in self.configuration.items():
            entries.append(f"{k}={v}")
        config_str = "\0".join(entries)
        if entries:
            config_str += "\0"

        config_bytes = config_str.encode("utf-8")
        # length = type(1) + reserved(1) + config_bytes
        length = 2 + len(config_bytes)
        header = struct.pack(">HBB", length, int(self.option_type), 0)
        raw = header + config_bytes

        # Pad to 4-byte boundary
        pad = (4 - (len(raw) % 4)) % 4
        return raw + b"\x00" * pad


def _deserialize_config_option(
    opt_type: SdOptionType, data: bytes, total_size: int
) -> Tuple[ConfigOption, int]:
    # data is after type + reserved
    config_str = data.rstrip(b"\0").decode("utf-8", errors="replace")
    configuration: Dict[str, str] = {}
    if config_str:
        for entry in config_str.split("\0"):
            if "=" in entry:
                k, v = entry.split("=", 1)
                configuration[k] = v

    option = ConfigOption(option_type=opt_type, configuration=configuration)
    return option, total_size


def _ipv6_to_bytes(address: str) -> bytes:
    """Convert IPv6 address string to 16 bytes."""
    import ipaddress
    addr = ipaddress.IPv6Address(address)
    return addr.packed


def _bytes_to_ipv6(data: bytes) -> str:
    """Convert 16 bytes to IPv6 address string."""
    import ipaddress
    addr = ipaddress.IPv6Address(data[:16])
    return str(addr)


@dataclass
class IPv6EndpointOption:
    """IPv6 endpoint option (type 0x06, 0x16, 0x26).

    After common header (type + reserved):
        [uint8 reserved] [uint8 L4 Proto] [uint16 port] [16 bytes IPv6 addr]
    Total data after length field: 1+1+1+2+16 = 21 bytes
    Length field value = 21
    Total with header = 23, padded to 24
    """

    option_type: SdOptionType = SdOptionType.IPv6_ENDPOINT
    address: str = "::1"
    port: int = 0
    protocol: int = 17  # 6=TCP, 17=UDP

    def serialize(self) -> bytes:
        addr_bytes = _ipv6_to_bytes(self.address)
        data = struct.pack(">BBH", 0, self.protocol, self.port) + addr_bytes
        length = 2 + len(data)  # type + reserved + payload
        header = struct.pack(">HBB", length, int(self.option_type), 0)
        raw = header + data
        # Pad to 4-byte boundary
        pad = (4 - (len(raw) % 4)) % 4
        return raw + b"\x00" * pad


def _deserialize_ipv6_option(
    opt_type: SdOptionType, data: bytes, total_size: int
) -> Tuple[IPv6EndpointOption, int]:
    """Deserialize IPv6 endpoint/multicast option."""
    # data after type(1) + reserved(1): reserved(1) + proto(1) + port(2) + addr(16)
    if len(data) < 19:
        raise MessageFormatError("IPv6 option data too short")

    _, protocol, port = struct.unpack_from(">BBH", data, 0)
    address = _bytes_to_ipv6(data[4:20])

    option = IPv6EndpointOption(
        option_type=opt_type,
        address=address,
        port=port,
        protocol=protocol,
    )
    return option, total_size
