"""SOME/IP container types: Struct, Array, DynamicArray, Enum, Map, Union."""

import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..config.protocol import ProtocolVersion
from ..error import SerializationError
from .primitives import TypeDescriptor, UInt32Type, UInt8Type


def _padding_bytes(current_offset: int, alignment: int) -> int:
    """Calculate padding bytes needed to align to the given boundary."""
    if alignment <= 1:
        return 0
    remainder = current_offset % alignment
    return (alignment - remainder) % alignment


class StructType(TypeDescriptor):
    """SOME/IP struct -- ordered fields, sequential layout with alignment padding.

    Fields are encoded sequentially. Each field is aligned to its natural alignment.
    Padding bytes (0x00) are inserted between fields as needed.
    The struct's overall alignment is the maximum alignment of its members.
    """

    def __init__(self, fields: List[Tuple[str, TypeDescriptor]]):
        self.fields = fields

    def encode(self, value: Any) -> bytes:
        if not isinstance(value, dict):
            raise SerializationError(
                f"Struct encode expected dict, got {type(value).__name__}"
            )
        result = bytearray()
        for field_name, field_type in self.fields:
            if field_name not in value:
                raise SerializationError(
                    f"Missing field '{field_name}' in struct"
                )
            # Alignment padding
            pad = _padding_bytes(len(result), field_type.alignment)
            result.extend(b"\x00" * pad)
            # Encode field value
            result.extend(field_type.encode(value[field_name]))
        return bytes(result)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        result: Dict[str, Any] = {}
        pos = offset
        for field_name, field_type in self.fields:
            # Alignment padding
            pad = _padding_bytes(pos, field_type.alignment)
            pos += pad
            # Decode field value
            value, consumed = field_type.decode(data, pos)
            result[field_name] = value
            pos += consumed
        return result, pos - offset

    def byte_length(self, value: Any = None) -> int:
        if value is None:
            raise SerializationError("Cannot compute byte_length of struct without value")
        length = 0
        for field_name, field_type in self.fields:
            pad = _padding_bytes(length, field_type.alignment)
            length += pad
            length += field_type.byte_length(value[field_name])
        return length

    @property
    def alignment(self) -> int:
        if not self.fields:
            return 1
        return max(ft.alignment for _, ft in self.fields)


class ArrayType(TypeDescriptor):
    """SOME/IP fixed-length array. No length prefix.

    Elements are encoded sequentially with individual alignment.
    The array's alignment is the element type's alignment.
    """

    def __init__(self, element_type: TypeDescriptor, length: int):
        self.element_type = element_type
        self.length = length

    def encode(self, value: Any) -> bytes:
        if len(value) != self.length:
            raise SerializationError(
                f"Fixed array length mismatch: expected {self.length}, got {len(value)}"
            )
        result = bytearray()
        for item in value:
            # Each element aligned within the array
            pad = _padding_bytes(len(result), self.element_type.alignment)
            result.extend(b"\x00" * pad)
            result.extend(self.element_type.encode(item))
        return bytes(result)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        result = []
        pos = offset
        for _ in range(self.length):
            pad = _padding_bytes(pos, self.element_type.alignment)
            pos += pad
            value, consumed = self.element_type.decode(data, pos)
            result.append(value)
            pos += consumed
        return result, pos - offset

    def byte_length(self, value: Any = None) -> int:
        length = 0
        for i in range(self.length):
            pad = _padding_bytes(length, self.element_type.alignment)
            length += pad
            if value is not None:
                length += self.element_type.byte_length(value[i])
            else:
                length += self.element_type.byte_length()
        return length

    @property
    def alignment(self) -> int:
        return self.element_type.alignment


class DynamicArrayType(TypeDescriptor):
    """SOME/IP variable-length array with uint32 length prefix.

    Format: [uint32 element_count] [element_0] [element_1] ...
    Alignment: 4 (due to uint32 length prefix)
    """

    def __init__(self, element_type: TypeDescriptor):
        self.element_type = element_type
        self._length_type = UInt32Type()

    def encode(self, value: Any) -> bytes:
        result = bytearray()
        result.extend(self._length_type.encode(len(value)))
        for item in value:
            pad = _padding_bytes(len(result), self.element_type.alignment)
            result.extend(b"\x00" * pad)
            result.extend(self.element_type.encode(item))
        return bytes(result)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        count, length_size = self._length_type.decode(data, offset)
        result = []
        pos = offset + length_size
        for _ in range(count):
            pad = _padding_bytes(pos, self.element_type.alignment)
            pos += pad
            value, consumed = self.element_type.decode(data, pos)
            result.append(value)
            pos += consumed
        return result, pos - offset

    def byte_length(self, value: Any = None) -> int:
        if value is None:
            return 4
        length = 4  # length prefix
        for item in value:
            pad = _padding_bytes(length, self.element_type.alignment)
            length += pad
            length += self.element_type.byte_length(item)
        return length

    @property
    def alignment(self) -> int:
        return 4


class EnumType(TypeDescriptor):
    """SOME/IP enum -- backed by an underlying integer type.

    The enum value is serialized as its underlying integer type.
    """

    def __init__(self, underlying_type: TypeDescriptor,
                 values: Optional[Dict[str, int]] = None):
        self.underlying_type = underlying_type
        self.values = values or {}

    def encode(self, value: Any) -> bytes:
        if isinstance(value, str):
            if value not in self.values:
                raise SerializationError(f"Unknown enum value: {value}")
            value = self.values[value]
        return self.underlying_type.encode(value)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        value, consumed = self.underlying_type.decode(data, offset)
        return value, consumed

    def byte_length(self, value: Any = None) -> int:
        return self.underlying_type.byte_length()

    @property
    def alignment(self) -> int:
        return self.underlying_type.alignment


class MapType(TypeDescriptor):
    """SOME/IP map (key-value pairs) with uint32 length prefix.

    Format: [uint32 length] [uint32 count] [key_0] [value_0] [key_1] [value_1] ...
    The length field covers everything after itself (count + all key-value pairs).
    Alignment: 4 (due to uint32 length prefix)
    """

    def __init__(self, key_type: TypeDescriptor, value_type: TypeDescriptor):
        self.key_type = key_type
        self.value_type = value_type
        self._length_type = UInt32Type()

    def encode(self, value: Any) -> bytes:
        if not isinstance(value, dict):
            raise SerializationError(
                f"Map encode expected dict, got {type(value).__name__}"
            )
        # Encode all key-value pairs first to compute length
        pairs_data = bytearray()
        pairs_data.extend(self._length_type.encode(len(value)))  # element count
        for k, v in value.items():
            pad_k = _padding_bytes(len(pairs_data), self.key_type.alignment)
            pairs_data.extend(b"\x00" * pad_k)
            pairs_data.extend(self.key_type.encode(k))
            pad_v = _padding_bytes(len(pairs_data), self.value_type.alignment)
            pairs_data.extend(b"\x00" * pad_v)
            pairs_data.extend(self.value_type.encode(v))

        # Length prefix covers count + all pairs data
        length_prefix = self._length_type.encode(len(pairs_data))
        return length_prefix + bytes(pairs_data)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        length, length_size = self._length_type.decode(data, offset)
        pos = offset + length_size

        # Read element count
        count, count_size = self._length_type.decode(data, pos)
        pos += count_size

        result: Dict[Any, Any] = {}
        for _ in range(count):
            pad_k = _padding_bytes(pos, self.key_type.alignment)
            pos += pad_k
            key, consumed = self.key_type.decode(data, pos)
            pos += consumed

            pad_v = _padding_bytes(pos, self.value_type.alignment)
            pos += pad_v
            val, consumed = self.value_type.decode(data, pos)
            pos += consumed

            result[key] = val

        return result, length_size + length

    def byte_length(self, value: Any = None) -> int:
        if value is None:
            return 4
        pairs_size = 4  # count field
        for k, v in value.items():
            pad_k = _padding_bytes(pairs_size, self.key_type.alignment)
            pairs_size += pad_k
            pairs_size += self.key_type.byte_length(k)
            pad_v = _padding_bytes(pairs_size, self.value_type.alignment)
            pairs_size += pad_v
            pairs_size += self.value_type.byte_length(v)
        return 4 + pairs_size  # length prefix + pairs data

    @property
    def alignment(self) -> int:
        return 4


class UnionType(TypeDescriptor):
    """SOME/IP union (tagged union / variant).

    v1.0:  [uint8 discriminator] [data]  (no length prefix)
    v1.1+: [uint32 length] [uint8 discriminator] [data]

    The length field (v1.1+) covers discriminator + data.
    Alignment: 4 (due to uint32 length prefix in v1.1+)
    """

    def __init__(
        self,
        cases: Dict[int, Tuple[str, TypeDescriptor]],
        protocol_version: ProtocolVersion = ProtocolVersion.V1_8_0,
        discriminator_type: Optional[TypeDescriptor] = None,
    ):
        self.cases = cases
        self.protocol_version = protocol_version
        self.discriminator_type = discriminator_type or UInt8Type()
        self._length_type = UInt32Type()

    def encode(self, value: Any) -> bytes:
        if not isinstance(value, dict) or len(value) != 1:
            raise SerializationError(
                "Union encode expects dict with single key {discriminator: data}"
            )
        disc, data = next(iter(value.items()))

        if disc not in self.cases:
            raise SerializationError(f"Unknown union discriminator: {disc}")

        case_name, case_type = self.cases[disc]
        disc_bytes = self.discriminator_type.encode(disc)
        data_bytes = case_type.encode(data)

        if self.protocol_version.supports_union_length_prefix:
            # v1.1+: [uint32 length] [uint8 discriminator] [data]
            inner_size = len(disc_bytes) + len(data_bytes)
            length_bytes = self._length_type.encode(inner_size)
            return length_bytes + disc_bytes + data_bytes
        else:
            # v1.0: [uint8 discriminator] [data]
            return disc_bytes + data_bytes

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        pos = offset

        if self.protocol_version.supports_union_length_prefix:
            # v1.1+: skip length prefix (used for validation)
            length, length_size = self._length_type.decode(data, pos)
            pos += length_size

        disc, disc_size = self.discriminator_type.decode(data, pos)
        pos += disc_size

        if disc not in self.cases:
            raise SerializationError(f"Unknown union discriminator: {disc}")

        case_name, case_type = self.cases[disc]
        value, consumed = case_type.decode(data, pos)
        pos += consumed

        return {disc: value}, pos - offset

    def byte_length(self, value: Any = None) -> int:
        if value is None:
            raise SerializationError("Cannot compute byte_length of union without value")
        disc, data = next(iter(value.items()))
        case_name, case_type = self.cases[disc]
        disc_len = self.discriminator_type.byte_length(disc)
        data_len = case_type.byte_length(data)

        if self.protocol_version.supports_union_length_prefix:
            return 4 + disc_len + data_len  # length prefix + disc + data
        else:
            return disc_len + data_len

    @property
    def alignment(self) -> int:
        if self.protocol_version.supports_union_length_prefix:
            return 4
        return self.discriminator_type.alignment
