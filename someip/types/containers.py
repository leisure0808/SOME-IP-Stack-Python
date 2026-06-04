"""SOME/IP container types: Struct, Array, DynamicArray, Enum, Map, Union, TaggedMember."""

import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..config.protocol import ProtocolVersion
from ..error import SerializationError
from .primitives import TypeDescriptor, UInt32Type, UInt8Type, UInt16Type


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


class WireType:
    """SOME/IP TLV Wire Type codes for tagged struct members.

    Per AUTOSAR SOME/IP v1.8.0 specification:
    - Wire types 0-3: base data types (8/16/32/64 bit)
    - Wire types 4-7: complex types with length field
    """

    BASE_8BIT = 0
    BASE_16BIT = 1
    BASE_32BIT = 2
    BASE_64BIT = 3
    COMPLEX_STATIC_LEN = 4   # Complex type with configured static length field size
    COMPLEX_8BIT_LEN = 5     # Complex type with 1-byte length field
    COMPLEX_16BIT_LEN = 6    # Complex type with 2-byte length field
    COMPLEX_32BIT_LEN = 7    # Complex type with 4-byte length field


@dataclass
class TaggedMember:
    """A tagged/optional struct member per AUTOSAR SOME/IP v1.8.0.

    Tagged members use a Tag-Length-Value (TLV) encoding:
    - Tag (2 bytes): wire_type (3 bits) + data_id (12 bits)
    - Length (variable): depends on wire_type
    - Value: the actual data

    Used for version-tolerant serialization where new fields can be added
    without breaking backward compatibility.
    """

    data_id: int           # 12-bit identifier, unique within a struct
    member_type: TypeDescriptor
    wire_type: int = 0     # Auto-detected if 0
    is_optional: bool = True

    def __post_init__(self):
        if self.data_id < 0 or self.data_id > 0xFFF:
            raise SerializationError(f"data_id must be 0-4095, got {self.data_id}")
        if self.wire_type == 0:
            self.wire_type = self._infer_wire_type()

    def _infer_wire_type(self) -> int:
        """Infer wire type from member_type alignment/size."""
        align = self.member_type.alignment
        if align <= 1:
            return WireType.BASE_8BIT
        elif align == 2:
            return WireType.BASE_16BIT
        elif align == 4:
            return WireType.BASE_32BIT
        elif align == 8:
            return WireType.BASE_64BIT
        else:
            return WireType.COMPLEX_32BIT_LEN

    def _encode_tag(self) -> bytes:
        """Encode the 2-byte Tag: [wire_type 3 bits][data_id 12 bits][reserved 1 bit]."""
        # Tag layout per AUTOSAR: byte0[6:4]=wire_type, byte0[3:0]+byte1[7]=data_id
        # Simplified: bits 15-13 = wire_type, bits 12-1 = data_id, bit 0 = reserved
        tag = ((self.wire_type & 0x07) << 13) | ((self.data_id & 0xFFF) << 1)
        return struct.pack(">H", tag)

    @staticmethod
    def _decode_tag(data: bytes, offset: int) -> Tuple[int, int, int]:
        """Decode a 2-byte Tag. Returns (wire_type, data_id, bytes_consumed)."""
        tag = struct.unpack_from(">H", data, offset)[0]
        wire_type = (tag >> 13) & 0x07
        data_id = (tag >> 1) & 0xFFF
        return wire_type, data_id, 2

    def encode_with_tag(self, value: Any) -> bytes:
        """Encode the tagged member: Tag + [Length] + Value."""
        tag_bytes = self._encode_tag()
        value_bytes = self.member_type.encode(value)

        if self.wire_type >= WireType.COMPLEX_STATIC_LEN:
            # Complex type: include length prefix
            if self.wire_type == WireType.COMPLEX_8BIT_LEN:
                length_bytes = struct.pack(">B", len(value_bytes))
            elif self.wire_type == WireType.COMPLEX_16BIT_LEN:
                length_bytes = struct.pack(">H", len(value_bytes))
            else:  # COMPLEX_32BIT_LEN or COMPLEX_STATIC_LEN
                length_bytes = struct.pack(">I", len(value_bytes))
            return tag_bytes + length_bytes + value_bytes
        else:
            # Base type: no length prefix
            return tag_bytes + value_bytes

    @staticmethod
    def decode_tagged(data: bytes, offset: int) -> Tuple[int, int, int]:
        """Decode just the Tag and length info. Returns (wire_type, data_id, total_tag_and_length_bytes)."""
        wire_type, data_id, tag_size = TaggedMember._decode_tag(data, offset)
        length_size = 0
        if wire_type >= WireType.COMPLEX_STATIC_LEN:
            if wire_type == WireType.COMPLEX_8BIT_LEN:
                length_size = 1
            elif wire_type == WireType.COMPLEX_16BIT_LEN:
                length_size = 2
            else:
                length_size = 4
        return wire_type, data_id, tag_size + length_size


class TaggedStructType(TypeDescriptor):
    """SOME/IP struct with tagged/optional members per v1.8.0.

    Supports a mix of regular (positional) fields and tagged fields.
    Regular fields are encoded first sequentially, then tagged fields
    are appended with Tag-Length-Value encoding.
    """

    def __init__(
        self,
        fields: List[Tuple[str, TypeDescriptor]],
        tagged_fields: Optional[List[Tuple[str, TaggedMember]]] = None,
    ):
        self.fields = fields
        self.tagged_fields = tagged_fields or []

    def encode(self, value: Any) -> bytes:
        if not isinstance(value, dict):
            raise SerializationError(
                f"TaggedStruct encode expected dict, got {type(value).__name__}"
            )
        result = bytearray()

        # Encode regular (positional) fields
        for field_name, field_type in self.fields:
            if field_name not in value:
                raise SerializationError(
                    f"Missing field '{field_name}' in struct"
                )
            pad = _padding_bytes(len(result), field_type.alignment)
            result.extend(b"\x00" * pad)
            result.extend(field_type.encode(value[field_name]))

        # Encode tagged fields (only if present in value dict)
        for field_name, tagged_member in self.tagged_fields:
            if field_name in value:
                result.extend(tagged_member.encode_with_tag(value[field_name]))

        return bytes(result)

    def decode(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        result: Dict[str, Any] = {}
        pos = offset

        # Decode regular (positional) fields
        for field_name, field_type in self.fields:
            pad = _padding_bytes(pos, field_type.alignment)
            pos += pad
            value, consumed = field_type.decode(data, pos)
            result[field_name] = value
            pos += consumed

        # Decode tagged fields
        tagged_lookup = {tm.data_id: (fn, tm) for fn, tm in self.tagged_fields}
        while pos < len(data):
            # Try to read a tag
            if pos + 2 > len(data):
                break
            wire_type, data_id, tag_and_length_size = TaggedMember.decode_tagged(data, pos)

            if data_id not in tagged_lookup:
                # Unknown tagged field - skip it
                # Need to determine the total size to skip
                skip = tag_and_length_size
                if wire_type >= WireType.COMPLEX_STATIC_LEN:
                    # Read the length to know how much data to skip
                    length_offset = pos + 2  # after tag
                    if wire_type == WireType.COMPLEX_8BIT_LEN and length_offset < len(data):
                        data_len = data[length_offset]
                        skip = 2 + 1 + data_len
                    elif wire_type == WireType.COMPLEX_16BIT_LEN and length_offset + 1 < len(data):
                        data_len = struct.unpack_from(">H", data, length_offset)[0]
                        skip = 2 + 2 + data_len
                    elif wire_type >= WireType.COMPLEX_32BIT_LEN and length_offset + 3 < len(data):
                        data_len = struct.unpack_from(">I", data, length_offset)[0]
                        skip = 2 + 4 + data_len
                    else:
                        break
                else:
                    # Base types: fixed size based on wire type
                    base_sizes = {0: 1, 1: 2, 2: 4, 3: 8}
                    skip = 2 + base_sizes.get(wire_type, 0)
                pos += skip
                continue

            field_name, tagged_member = tagged_lookup[data_id]
            # Skip past tag and optional length
            pos += tag_and_length_size
            # Decode the value
            value, consumed = tagged_member.member_type.decode(data, pos)
            result[field_name] = value
            pos += consumed

        return result, pos - offset

    def byte_length(self, value: Any = None) -> int:
        if value is None:
            raise SerializationError("Cannot compute byte_length of TaggedStruct without value")
        length = 0
        for field_name, field_type in self.fields:
            pad = _padding_bytes(length, field_type.alignment)
            length += pad
            length += field_type.byte_length(value[field_name])
        for field_name, tagged_member in self.tagged_fields:
            if field_name in value:
                # Tag (2) + optional length + value
                encoded = tagged_member.encode_with_tag(value[field_name])
                length += len(encoded)
        return length

    @property
    def alignment(self) -> int:
        if not self.fields:
            return 1
        return max(ft.alignment for _, ft in self.fields)
