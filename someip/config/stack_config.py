"""Stack-level configuration."""

from dataclasses import dataclass, field
from typing import Optional

from .protocol import ProtocolVersion


@dataclass
class StackConfiguration:
    """Global SOME/IP stack configuration.

    Controls transport, protocol version, timing, and other
    stack-wide behavior.
    """

    protocol_version: ProtocolVersion = ProtocolVersion.V1_8_0
    # MTU for TP segmentation (bytes). Typical UDP MTU ~1400.
    tp_mtu: int = 1392
    # Maximum time to wait for TP reassembly (seconds)
    tp_reassembly_timeout: float = 5.0
    # Maximum time to wait for a request response (seconds)
    request_timeout: float = 5.0
    # Local unicast address for SD
    unicast_address: str = "127.0.0.1"
    # SD multicast address
    sd_multicast_address: str = "224.224.224.245"
    # SD port
    sd_port: int = 30490
    # Logging level
    log_level: str = "INFO"
