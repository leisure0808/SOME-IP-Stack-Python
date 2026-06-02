"""SOME/IP service interface base class."""

from typing import Dict, Optional

from ..config.service_config import ServiceInterfaceConfig


class ServiceInterface:
    """Base class for SOME/IP service interfaces.

    Provides the common interface for both Skeleton (server) and
    Proxy (client) implementations.
    """

    def __init__(self, config: ServiceInterfaceConfig):
        self._config = config

    @property
    def service_id(self) -> int:
        return self._config.service_id

    @property
    def instance_id(self) -> int:
        return self._config.instance_id

    @property
    def major_version(self) -> int:
        return self._config.major_version

    @property
    def minor_version(self) -> int:
        return self._config.minor_version

    @property
    def interface_version(self) -> int:
        return self._config.interface_version

    @property
    def config(self) -> ServiceInterfaceConfig:
        return self._config
