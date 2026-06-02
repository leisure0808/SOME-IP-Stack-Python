"""SOME/IP string and byte string types with serialization."""

import struct
from typing import Any, Optional, Tuple

from .primitives import TypeDescriptor, UInt32Type


class StringType(TypeDescriptor):
    """SOME/IP string with uint32 length prefix.

    Format: [uint32 length] [string bytes] [null terminator if null_terminated]
    Alignment: 4 (due to uint32 length prefix)
    """

    def __init__(self, encoding: str = "utf-8", null_terminated: bool = False):
        self.encoding = encoding
        self.null_terminated = null_terminated
        self._length_type = UInt32Type()

    def encode(self, value: Any) -> bytes:
        if value is None:
            value = ""
        encoded = value.encode(self.encoding)
        if self.null_terminated:
            encoded += b"\x00"
        length_prefix = self._length_type.encode(len(encoded))
        return length_prefix + encoded

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        length, length_size = self._length_type.decode(data, offset)
        str_start = offset + length_size
        str_bytes = data[str_start:str_start + length]
        value = str_bytes.decode(self.encoding)
        if self.null_terminated and value.endswith("\x00"):
            value = value[:-1]
        return value, length_size + length

    def byte_length(self, value: Any = None) -> int:
        if value is None:
            value = ""
        encoded = value.encode(self.encoding)
        if self.null_terminated:
            encoded += b"\x00"
        return 4 + len(encoded)

    @property
    def alignment(self) -> int:
        return 4


class ByteStringType(TypeDescriptor):
    """SOME/IP byte array with uint32 length prefix.

    Format: [uint32 length] [byte data]
    Alignment: 4 (due to uint32 length prefix)
    """

    def __init__(self):
        self._length_type = UInt32Type()

    def encode(self, value: Any) -> bytes:
        if value is None:
            value = b""
        length_prefix = self._length_type.encode(len(value))
        return length_prefix + value

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        length, length_size = self._length_type.decode(data, offset)
        byte_start = offset + length_size
        value = data[byte_start:byte_start + length]
        return value, length_size + length

    def byte_length(self, value: Any = None) -> int:
        if value is None:
            return 4
        return 4 + len(value)

    @property
    def alignment(self) -> int:
        return 4
