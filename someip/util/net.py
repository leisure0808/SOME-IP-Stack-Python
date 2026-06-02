"""Network utility functions."""

import socket
from typing import Optional


def get_free_port() -> int:
    """Find a free TCP/UDP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def is_multicast_address(address: str) -> bool:
    """Check if an IP address is in the multicast range (224.0.0.0 - 239.255.255.255)."""
    try:
        first_octet = int(address.split(".")[0])
        return 224 <= first_octet <= 239
    except (ValueError, IndexError):
        return False
