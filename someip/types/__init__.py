"""SOME/IP type system and serialization."""

from .primitives import (
    TypeDescriptor,
    BoolType,
    UInt8Type, UInt16Type, UInt32Type, UInt64Type,
    Int8Type, Int16Type, Int32Type, Int64Type,
    FloatType, DoubleType,
)
from .strings import StringType, ByteStringType
from .containers import (
    StructType, ArrayType, DynamicArrayType,
    EnumType, MapType, UnionType,
)
from .codec import Codec
from .type_registry import TypeRegistry

__all__ = [
    "TypeDescriptor",
    "BoolType",
    "UInt8Type", "UInt16Type", "UInt32Type", "UInt64Type",
    "Int8Type", "Int16Type", "Int32Type", "Int64Type",
    "FloatType", "DoubleType",
    "StringType", "ByteStringType",
    "StructType", "ArrayType", "DynamicArrayType",
    "EnumType", "MapType", "UnionType",
    "Codec",
    "TypeRegistry",
]
