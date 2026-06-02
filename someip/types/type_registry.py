"""Global type registry for named SOME/IP types."""

from typing import Dict, Optional

from .primitives import TypeDescriptor


class TypeRegistry:
    """Registry for named SOME/IP type descriptors.

    Allows referencing types by name, useful for recursive types
    and shared type definitions.
    """

    def __init__(self):
        self._types: Dict[str, TypeDescriptor] = {}

    def register(self, name: str, descriptor: TypeDescriptor) -> None:
        """Register a type descriptor under a name."""
        self._types[name] = descriptor

    def get(self, name: str) -> Optional[TypeDescriptor]:
        """Look up a type descriptor by name."""
        return self._types.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._types

    def __getitem__(self, name: str) -> TypeDescriptor:
        return self._types[name]
