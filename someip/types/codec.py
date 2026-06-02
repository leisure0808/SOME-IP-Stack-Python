"""SOME/IP codec engine -- central serialization dispatcher."""

from typing import Any, Tuple

from ..config.protocol import ProtocolVersion
from ..error import SerializationError
from .containers import (
    ArrayType,
    DynamicArrayType,
    EnumType,
    MapType,
    StructType,
    UnionType,
)
from .primitives import TypeDescriptor
from .strings import ByteStringType, StringType


class Codec:
    """Central serialization engine for SOME/IP types.

    Handles alignment, length prefixes, and nested types.
    All serialization is big-endian per SOME/IP spec.
    """

    def __init__(
        self, protocol_version: ProtocolVersion = ProtocolVersion.V1_8_0
    ):
        self.protocol_version = protocol_version

    def encode(self, descriptor: TypeDescriptor, value: Any) -> bytes:
        """Encode a value using the given type descriptor."""
        return descriptor.encode(value)

    def decode(
        self, descriptor: TypeDescriptor, data: bytes, offset: int = 0
    ) -> Tuple[Any, int]:
        """Decode bytes using the given type descriptor.

        Returns (value, bytes_consumed).
        """
        return descriptor.decode(data, offset)

    def encode_struct(self, descriptor: StructType, value: dict) -> bytes:
        """Encode a struct, applying alignment padding between fields."""
        return descriptor.encode(value)

    def decode_struct(
        self, descriptor: StructType, data: bytes, offset: int = 0
    ) -> Tuple[dict, int]:
        """Decode a struct, respecting alignment."""
        return descriptor.decode(data, offset)
