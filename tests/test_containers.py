"""Tests for container type serialization (Struct, Array, Enum, Map, Union)."""

import pytest

from someip.config.protocol import ProtocolVersion
from someip.error import SerializationError
from someip.types.primitives import (
    UInt8Type,
    UInt16Type,
    UInt32Type,
    UInt64Type,
    Int32Type,
)
from someip.types.strings import StringType, ByteStringType
from someip.types.containers import (
    StructType,
    ArrayType,
    DynamicArrayType,
    EnumType,
    MapType,
    UnionType,
)


class TestStructType:
    def test_simple_struct(self):
        """Struct with two uint32 fields, no padding needed."""
        s = StructType([("a", UInt32Type()), ("b", UInt32Type())])
        data = s.encode({"a": 1, "b": 2})
        val, consumed = s.decode(data)
        assert val == {"a": 1, "b": 2}
        assert consumed == 8

    def test_struct_with_alignment_padding(self):
        """Struct with uint8 followed by uint32 requires 3 bytes padding."""
        s = StructType([("x", UInt8Type()), ("y", UInt32Type())])
        data = s.encode({"x": 0x42, "y": 0x12345678})
        # x(1) + padding(3) + y(4) = 8 bytes
        assert len(data) == 8
        assert data[0] == 0x42
        assert data[1:4] == b"\x00\x00\x00"  # padding
        val, consumed = s.decode(data)
        assert val == {"x": 0x42, "y": 0x12345678}

    def test_struct_alignment_is_max_member(self):
        """Struct alignment = max alignment of its members."""
        s = StructType([("a", UInt8Type()), ("b", UInt64Type())])
        assert s.alignment == 8

    def test_empty_struct(self):
        s = StructType([])
        data = s.encode({})
        val, consumed = s.decode(data)
        assert val == {}
        assert consumed == 0
        assert s.alignment == 1

    def test_struct_missing_field_raises(self):
        s = StructType([("a", UInt32Type())])
        with pytest.raises(SerializationError, match="Missing field"):
            s.encode({})

    def test_struct_wrong_type_raises(self):
        s = StructType([("a", UInt32Type())])
        with pytest.raises(SerializationError, match="expected dict"):
            s.encode("not a dict")

    def test_nested_struct(self):
        inner = StructType([("x", UInt16Type()), ("y", UInt16Type())])
        outer = StructType([("id", UInt32Type()), ("inner", inner)])
        data = outer.encode({"id": 100, "inner": {"x": 1, "y": 2}})
        val, consumed = outer.decode(data)
        assert val == {"id": 100, "inner": {"x": 1, "y": 2}}


class TestArrayType:
    def test_fixed_array(self):
        a = ArrayType(UInt8Type(), 3)
        data = a.encode([1, 2, 3])
        assert data == b"\x01\x02\x03"
        val, consumed = a.decode(data)
        assert val == [1, 2, 3]

    def test_fixed_array_wrong_length(self):
        a = ArrayType(UInt8Type(), 3)
        with pytest.raises(SerializationError, match="length mismatch"):
            a.encode([1, 2])

    def test_fixed_array_alignment(self):
        a = ArrayType(UInt16Type(), 2)
        assert a.alignment == 2

    def test_fixed_array_uint32(self):
        a = ArrayType(UInt32Type(), 2)
        data = a.encode([0x11111111, 0x22222222])
        val, consumed = a.decode(data)
        assert val == [0x11111111, 0x22222222]
        assert consumed == 8

    def test_roundtrip(self):
        a = ArrayType(UInt32Type(), 4)
        values = [0, 1, 100, 0xFFFFFFFF]
        assert a.decode(a.encode(values))[0] == values


class TestDynamicArrayType:
    def test_dynamic_array(self):
        a = DynamicArrayType(UInt8Type())
        data = a.encode([1, 2, 3])
        val, consumed = a.decode(data)
        assert val == [1, 2, 3]
        # 4 (length) + 3 (elements) = 7
        assert consumed == 7

    def test_empty_dynamic_array(self):
        a = DynamicArrayType(UInt8Type())
        data = a.encode([])
        val, consumed = a.decode(data)
        assert val == []
        assert consumed == 4  # just the length prefix

    def test_dynamic_array_alignment(self):
        a = DynamicArrayType(UInt32Type())
        assert a.alignment == 4

    def test_roundtrip(self):
        a = DynamicArrayType(UInt32Type())
        values = [10, 20, 30]
        assert a.decode(a.encode(values))[0] == values


class TestEnumType:
    def test_enum_uint8(self):
        e = EnumType(UInt8Type(), {"RED": 1, "GREEN": 2, "BLUE": 3})
        data = e.encode("GREEN")
        assert data == b"\x02"
        val, consumed = e.decode(data)
        assert val == 2
        assert consumed == 1

    def test_enum_int_value(self):
        e = EnumType(UInt8Type(), {"A": 0, "B": 1})
        data = e.encode(1)
        val, consumed = e.decode(data)
        assert val == 1

    def test_enum_unknown_value_raises(self):
        e = EnumType(UInt8Type(), {"A": 0})
        with pytest.raises(SerializationError, match="Unknown enum"):
            e.encode("UNKNOWN")

    def test_enum_alignment(self):
        e = EnumType(UInt32Type())
        assert e.alignment == 4


class TestMapType:
    def test_simple_map(self):
        m = MapType(UInt16Type(), UInt32Type())
        data = m.encode({1: 100, 2: 200})
        val, consumed = m.decode(data)
        assert val == {1: 100, 2: 200}

    def test_empty_map(self):
        m = MapType(UInt16Type(), UInt32Type())
        data = m.encode({})
        val, consumed = m.decode(data)
        assert val == {}

    def test_map_alignment(self):
        m = MapType(UInt8Type(), UInt8Type())
        assert m.alignment == 4

    def test_map_wrong_type_raises(self):
        m = MapType(UInt8Type(), UInt8Type())
        with pytest.raises(SerializationError, match="expected dict"):
            m.encode([1, 2])


class TestUnionType:
    def test_union_v18_with_length_prefix(self):
        u = UnionType(
            cases={0: ("none", UInt32Type()), 1: ("value", UInt32Type())},
            protocol_version=ProtocolVersion.V1_8_0,
        )
        data = u.encode({1: 42})
        # v1.1+: [uint32 length] [uint8 disc] [uint32 data]
        # length = 1(disc) + 4(data) = 5
        assert len(data) == 4 + 1 + 4  # 9 bytes
        val, consumed = u.decode(data)
        assert val == {1: 42}

    def test_union_v10_no_length_prefix(self):
        u = UnionType(
            cases={0: ("none", UInt32Type()), 1: ("value", UInt32Type())},
            protocol_version=ProtocolVersion.V1_0,
        )
        data = u.encode({1: 42})
        # v1.0: [uint8 disc] [uint32 data]
        assert len(data) == 1 + 4  # 5 bytes
        val, consumed = u.decode(data)
        assert val == {1: 42}

    def test_union_alignment_v18(self):
        u = UnionType(
            cases={0: ("none", UInt32Type())},
            protocol_version=ProtocolVersion.V1_8_0,
        )
        assert u.alignment == 4

    def test_union_alignment_v10(self):
        u = UnionType(
            cases={0: ("none", UInt32Type())},
            protocol_version=ProtocolVersion.V1_0,
        )
        assert u.alignment == 1  # discriminator alignment

    def test_union_unknown_discriminator_raises(self):
        u = UnionType(
            cases={0: ("none", UInt32Type())},
            protocol_version=ProtocolVersion.V1_8_0,
        )
        with pytest.raises(SerializationError, match="Unknown union"):
            u.encode({99: 42})

    def test_union_wrong_value_format_raises(self):
        u = UnionType(
            cases={0: ("none", UInt32Type())},
            protocol_version=ProtocolVersion.V1_8_0,
        )
        with pytest.raises(SerializationError, match="single key"):
            u.encode("not a dict")


class TestStringType:
    def test_string_encode_decode(self):
        s = StringType()
        data = s.encode("hello")
        val, consumed = s.decode(data)
        assert val == "hello"
        # 4 (length) + 5 (bytes) = 9
        assert consumed == 9

    def test_null_terminated_string(self):
        s = StringType(null_terminated=True)
        data = s.encode("hello")
        # "hello" + null = 6 bytes
        val, consumed = s.decode(data)
        assert val == "hello"

    def test_empty_string(self):
        s = StringType()
        data = s.encode("")
        val, consumed = s.decode(data)
        assert val == ""

    def test_string_alignment(self):
        s = StringType()
        assert s.alignment == 4


class TestByteStringType:
    def test_bytes_encode_decode(self):
        b = ByteStringType()
        data = b.encode(b"\x01\x02\x03")
        val, consumed = b.decode(data)
        assert val == b"\x01\x02\x03"

    def test_empty_bytes(self):
        b = ByteStringType()
        data = b.encode(b"")
        val, consumed = b.decode(data)
        assert val == b""

    def test_byte_string_alignment(self):
        b = ByteStringType()
        assert b.alignment == 4
