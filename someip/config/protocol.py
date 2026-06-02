"""SOME/IP protocol version definitions."""

from enum import Enum


class ProtocolVersion(Enum):
    """SOME/IP protocol versions.

    Each value is a tuple of (protocol_version, interface_version)
    as used in the SOME/IP header fields.
    """

    V1_0 = (1, 0)
    V1_1 = (1, 1)
    V1_2 = (1, 2)
    V1_3 = (1, 3)
    V1_4 = (1, 4)
    V1_5 = (1, 5)
    V1_6 = (1, 6)
    V1_7 = (1, 7)
    V1_8_0 = (1, 8)

    @property
    def protocol_version(self) -> int:
        """Protocol version field value (always 1 for SOME/IP)."""
        return self.value[0]

    @property
    def interface_version(self) -> int:
        """Interface version field value."""
        return self.value[1]

    @property
    def supports_tp(self) -> bool:
        """Whether this version supports SOME/IP-TP (v1.5+)."""
        return self.interface_version >= 5

    @property
    def supports_union_length_prefix(self) -> bool:
        """Whether unions include a length prefix (v1.1+)."""
        return self.interface_version >= 1

    @property
    def supports_e2e(self) -> bool:
        """Whether this version supports E2E protection (v1.8.0)."""
        return self.interface_version >= 8
