"""SOME/IP method descriptor."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Method:
    """Describes a SOME/IP service method.

    Method IDs for regular methods: 0x0001 - 0x7FFF
    Method IDs for getter/setter (fields): 0x0001 - 0x7FFF with specific offsets
    """

    method_id: int
    name: str = ""
    request_type: Optional[str] = None
    response_type: Optional[str] = None
    fire_and_forget: bool = False
