"""Service interface configuration data classes."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class MethodConfig:
    """Configuration for a single service method."""

    method_id: int
    request_type: Optional[str] = None  # TypeDescriptor name or None
    response_type: Optional[str] = None  # TypeDescriptor name or None
    fire_and_forget: bool = False


@dataclass
class EventConfig:
    """Configuration for a single service event."""

    event_id: int
    eventgroup_id: int
    event_type: Optional[str] = None  # TypeDescriptor name


@dataclass
class FieldConfig:
    """Configuration for a service field (getter/setter/notifier)."""

    field_id: int
    getter_id: Optional[int] = None  # method_id for getter
    setter_id: Optional[int] = None  # method_id for setter
    notifier_id: Optional[int] = None  # event_id for notifier
    eventgroup_id: Optional[int] = None
    field_type: Optional[str] = None  # TypeDescriptor name


@dataclass
class ServiceInterfaceConfig:
    """Configuration for a complete service interface."""

    service_id: int
    instance_id: int
    major_version: int = 1
    minor_version: int = 0
    interface_version: int = 1
    methods: Dict[int, MethodConfig] = field(default_factory=dict)
    events: Dict[int, EventConfig] = field(default_factory=dict)
    fields: Dict[int, FieldConfig] = field(default_factory=dict)
