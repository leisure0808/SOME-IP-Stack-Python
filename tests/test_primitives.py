"""Tests for primitive type serialization."""

import struct
import math

import pytest

from someip.types.primitives import (
    BoolType,
    UInt8Type,
    UInt16Type,
    UInt32Type,
    UInt64Type,
    Int8Type,
    Int16Type,
    Int32Type,
    Int64Type,
    FloatType,
    DoubleType,
)


class TestBoolType:
    def setup_method(self):
        self.t = BoolType()

    def test_encode_true(self):
        assert self.t.encode(True) == b"\x01"

    def test_encode_false(self):
        assert self.t.encode(False) == b"\x00"

    def test_decode_true(self):
        val, consumed = self.t.decode(b"\x01")
        assert val is True
        assert consumed == 1

    def test_decode_false(self):
        val, consumed = self.t.decode(b"\x00")
        assert val is False
        assert consumed == 1

    def test_decode_nonzero(self):
        val, consumed = self.t.decode(b"\x02")
        assert val is True

    def test_roundtrip(self):
        for v in (True, False):
            assert self.t.decode(self.t.encode(v))[0] == v

    def test_byte_length(self):
        assert self.t.byte_length() == 1

    def test_alignment(self):
        assert self.t.alignment == 1


class TestUInt8Type:
    def setup_method(self):
        self.t = UInt8Type()

    def test_encode_min(self):
        assert self.t.encode(0) == b"\x00"

    def test_encode_max(self):
        assert self.t.encode(255) == b"\xff"

    def test_decode(self):
        val, consumed = self.t.decode(b"\x42")
        assert val == 0x42
        assert consumed == 1

    def test_roundtrip(self):
        for v in (0, 1, 127, 255):
            assert self.t.decode(self.t.encode(v))[0] == v

    def test_byte_length(self):
        assert self.t.byte_length() == 1

    def test_alignment(self):
        assert self.t.alignment == 1


class TestUInt16Type:
    def setup_method(self):
        self.t = UInt16Type()

    def test_encode(self):
        assert self.t.encode(0x1234) == b"\x12\x34"

    def test_decode(self):
        val, consumed = self.t.decode(b"\xab\xcd")
        assert val == 0xABCD
        assert consumed == 2

    def test_roundtrip(self):
        for v in (0, 1, 0x7FFF, 0xFFFF):
            assert self.t.decode(self.t.encode(v))[0] == v

    def test_byte_length(self):
        assert self.t.byte_length() == 2

    def test_alignment(self):
        assert self.t.alignment == 2


class TestUInt32Type:
    def setup_method(self):
        self.t = UInt32Type()

    def test_encode(self):
        assert self.t.encode(0x12345678) == b"\x12\x34\x56\x78"

    def test_decode(self):
        val, consumed = self.t.decode(b"\x00\x01\x02\x03")
        assert val == 0x00010203
        assert consumed == 4

    def test_roundtrip(self):
        for v in (0, 1, 0x7FFFFFFF, 0xFFFFFFFF):
            assert self.t.decode(self.t.encode(v))[0] == v

    def test_byte_length(self):
        assert self.t.byte_length() == 4

    def test_alignment(self):
        assert self.t.alignment == 4


class TestUInt64Type:
    def setup_method(self):
        self.t = UInt64Type()

    def test_encode(self):
        expected = struct.pack(">Q", 0x0102030405060708)
        assert self.t.encode(0x0102030405060708) == expected

    def test_roundtrip(self):
        for v in (0, 1, 2**63 - 1, 2**64 - 1):
            assert self.t.decode(self.t.encode(v))[0] == v

    def test_byte_length(self):
        assert self.t.byte_length() == 8

    def test_alignment(self):
        assert self.t.alignment == 8


class TestInt8Type:
    def setup_method(self):
        self.t = Int8Type()

    def test_encode_negative(self):
        assert self.t.encode(-1) == b"\xff"

    def test_roundtrip(self):
        for v in (-128, -1, 0, 1, 127):
            assert self.t.decode(self.t.encode(v))[0] == v

    def test_alignment(self):
        assert self.t.alignment == 1


class TestInt16Type:
    def setup_method(self):
        self.t = Int16Type()

    def test_roundtrip(self):
        for v in (-32768, -1, 0, 1, 32767):
            assert self.t.decode(self.t.encode(v))[0] == v

    def test_alignment(self):
        assert self.t.alignment == 2


class TestInt32Type:
    def setup_method(self):
        self.t = Int32Type()

    def test_roundtrip(self):
        for v in (-2147483648, -1, 0, 1, 2147483647):
            assert self.t.decode(self.t.encode(v))[0] == v

    def test_alignment(self):
        assert self.t.alignment == 4


class TestInt64Type:
    def setup_method(self):
        self.t = Int64Type()

    def test_roundtrip(self):
        for v in (-(2**63), -1, 0, 1, 2**63 - 1):
            assert self.t.decode(self.t.encode(v))[0] == v

    def test_alignment(self):
        assert self.t.alignment == 8


class TestFloatType:
    def setup_method(self):
        self.t = FloatType()

    def test_encode(self):
        data = self.t.encode(1.0)
        assert data == struct.pack(">f", 1.0)

    def test_roundtrip(self):
        for v in (0.0, 1.0, -1.0, 3.14, float("inf"), float("-inf")):
            result = self.t.decode(self.t.encode(v))[0]
            if math.isinf(v):
                assert math.isinf(result)
            else:
                assert abs(result - v) < 1e-6

    def test_byte_length(self):
        assert self.t.byte_length() == 4

    def test_alignment(self):
        assert self.t.alignment == 4


class TestDoubleType:
    def setup_method(self):
        self.t = DoubleType()

    def test_roundtrip(self):
        for v in (0.0, 1.0, -1.0, 3.141592653589793, float("inf")):
            result = self.t.decode(self.t.encode(v))[0]
            if math.isinf(v):
                assert math.isinf(result)
            else:
                assert abs(result - v) < 1e-12

    def test_byte_length(self):
        assert self.t.byte_length() == 8

    def test_alignment(self):
        assert self.t.alignment == 8


class TestDecodeWithOffset:
    """Test that decode works with non-zero offset."""

    def test_uint32_with_offset(self):
        t = UInt32Type()
        data = b"\x00\x00" + b"\x12\x34\x56\x78" + b"\x00\x00"
        val, consumed = t.decode(data, offset=2)
        assert val == 0x12345678
        assert consumed == 4

    def test_uint16_with_offset(self):
        t = UInt16Type()
        data = b"\x00" + b"\xab\xcd"
        val, consumed = t.decode(data, offset=1)
        assert val == 0xABCD
        assert consumed == 2
