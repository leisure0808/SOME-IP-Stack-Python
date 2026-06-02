"""SOME/IP primitive data types with serialization."""

import struct
from abc import ABC, abstractmethod
from typing import Any, Tuple


class TypeDescriptor(ABC):
    """Base class for all SOME/IP type descriptors.

    Provides encode/decode/byte_length/alignment interface.
    All serialization is big-endian per SOME/IP spec.
    """

    @abstractmethod
    def encode(self, value: Any) -> bytes:
        """Serialize a Python value to bytes."""

    @abstractmethod
    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        """Deserialize bytes to a Python value.

        Returns (value, bytes_consumed) starting from offset.
        """

    @abstractmethod
    def byte_length(self, value: Any = None) -> int:
        """Return the byte length of the serialized form."""

    @property
    @abstractmethod
    def alignment(self) -> int:
        """Byte alignment requirement (1, 2, 4, or 8)."""


class BoolType(TypeDescriptor):
    """SOME/IP bool: 1 byte, 0x00=False, 0x01=True."""

    def encode(self, value: Any) -> bytes:
        return struct.pack(">B", 0x01 if value else 0x00)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        v = struct.unpack_from(">B", data, offset)[0]
        return bool(v), 1

    def byte_length(self, value: Any = None) -> int:
        return 1

    @property
    def alignment(self) -> int:
        return 1


class UInt8Type(TypeDescriptor):
    """SOME/IP uint8: 1 byte, unsigned."""

    def encode(self, value: Any) -> bytes:
        return struct.pack(">B", value)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        v = struct.unpack_from(">B", data, offset)[0]
        return v, 1

    def byte_length(self, value: Any = None) -> int:
        return 1

    @property
    def alignment(self) -> int:
        return 1


class UInt16Type(TypeDescriptor):
    """SOME/IP uint16: 2 bytes, unsigned, big-endian."""

    def encode(self, value: Any) -> bytes:
        return struct.pack(">H", value)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        v = struct.unpack_from(">H", data, offset)[0]
        return v, 2

    def byte_length(self, value: Any = None) -> int:
        return 2

    @property
    def alignment(self) -> int:
        return 2


class UInt32Type(TypeDescriptor):
    """SOME/IP uint32: 4 bytes, unsigned, big-endian."""

    def encode(self, value: Any) -> bytes:
        return struct.pack(">I", value)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        v = struct.unpack_from(">I", data, offset)[0]
        return v, 4

    def byte_length(self, value: Any = None) -> int:
        return 4

    @property
    def alignment(self) -> int:
        return 4


class UInt64Type(TypeDescriptor):
    """SOME/IP uint64: 8 bytes, unsigned, big-endian."""

    def encode(self, value: Any) -> bytes:
        return struct.pack(">Q", value)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        v = struct.unpack_from(">Q", data, offset)[0]
        return v, 8

    def byte_length(self, value: Any = None) -> int:
        return 8

    @property
    def alignment(self) -> int:
        return 8


class Int8Type(TypeDescriptor):
    """SOME/IP int8: 1 byte, signed."""

    def encode(self, value: Any) -> bytes:
        return struct.pack(">b", value)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        v = struct.unpack_from(">b", data, offset)[0]
        return v, 1

    def byte_length(self, value: Any = None) -> int:
        return 1

    @property
    def alignment(self) -> int:
        return 1


class Int16Type(TypeDescriptor):
    """SOME/IP int16: 2 bytes, signed, big-endian."""

    def encode(self, value: Any) -> bytes:
        return struct.pack(">h", value)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        v = struct.unpack_from(">h", data, offset)[0]
        return v, 2

    def byte_length(self, value: Any = None) -> int:
        return 2

    @property
    def alignment(self) -> int:
        return 2


class Int32Type(TypeDescriptor):
    """SOME/IP int32: 4 bytes, signed, big-endian."""

    def encode(self, value: Any) -> bytes:
        return struct.pack(">i", value)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        v = struct.unpack_from(">i", data, offset)[0]
        return v, 4

    def byte_length(self, value: Any = None) -> int:
        return 4

    @property
    def alignment(self) -> int:
        return 4


class Int64Type(TypeDescriptor):
    """SOME/IP int64: 8 bytes, signed, big-endian."""

    def encode(self, value: Any) -> bytes:
        return struct.pack(">q", value)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        v = struct.unpack_from(">q", data, offset)[0]
        return v, 8

    def byte_length(self, value: Any = None) -> int:
        return 8

    @property
    def alignment(self) -> int:
        return 8


class FloatType(TypeDescriptor):
    """SOME/IP float32: 4 bytes, IEEE 754, big-endian."""

    def encode(self, value: Any) -> bytes:
        return struct.pack(">f", value)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        v = struct.unpack_from(">f", data, offset)[0]
        return v, 4

    def byte_length(self, value: Any = None) -> int:
        return 4

    @property
    def alignment(self) -> int:
        return 4


class DoubleType(TypeDescriptor):
    """SOME/IP float64: 8 bytes, IEEE 754, big-endian."""

    def encode(self, value: Any) -> bytes:
        return struct.pack(">d", value)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        v = struct.unpack_from(">d", data, offset)[0]
        return v, 8

    def byte_length(self, value: Any = None) -> int:
        return 8

    @property
    def alignment(self) -> int:
        return 8
