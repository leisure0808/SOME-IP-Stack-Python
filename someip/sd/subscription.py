"""SOME/IP Service Discovery subscription state tracking."""

from dataclasses import dataclass, field
from typing import Dict, Optional, Set


@dataclass
class SubscriptionState:
    """Tracks the state of an eventgroup subscription."""

    service_id: int
    instance_id: int
    eventgroup_id: int
    major_version: int
    remote_address: str = ""
    remote_port: int = 0
    is_subscribed: bool = False
    reference_count: int = 0


@dataclass
class OfferedService:
    """Tracks a service that has been offered (received OfferService)."""

    service_id: int
    instance_id: int
    major_version: int
    minor_version: int
    ttl: int
    address: str = "0.0.0.0"
    port: int = 0
    protocol: int = 17  # UDP
    eventgroups: Set[int] = field(default_factory=set)


class SubscriptionManager:
    """Manages service offers and eventgroup subscriptions."""

    def __init__(self):
        # Key: (service_id, instance_id)
        self._offered_services: Dict[tuple, OfferedService] = {}
        # Key: (service_id, instance_id, eventgroup_id)
        self._subscriptions: Dict[tuple, SubscriptionState] = {}

    def update_offer(self, entry) -> None:
        """Update offered service from an SD entry."""
        key = (entry.service_id, entry.instance_id)

        if entry.ttl == 0:
            # Stop offer
            self._offered_services.pop(key, None)
        else:
            offer = self._offered_services.get(key)
            if offer:
                offer.major_version = entry.major_version
                offer.minor_version = entry.minor_version
                offer.ttl = entry.ttl
            else:
                self._offered_services[key] = OfferedService(
                    service_id=entry.service_id,
                    instance_id=entry.instance_id,
                    major_version=entry.major_version,
                    minor_version=entry.minor_version,
                    ttl=entry.ttl,
                )

    def update_offer_endpoint(self, service_id: int, instance_id: int,
                               address: str, port: int, protocol: int = 17) -> None:
        """Update the endpoint for an offered service."""
        key = (service_id, instance_id)
        offer = self._offered_services.get(key)
        if offer:
            offer.address = address
            offer.port = port
            offer.protocol = protocol

    def get_offered_service(self, service_id: int, instance_id: int) -> Optional[OfferedService]:
        """Get an offered service by ID."""
        return self._offered_services.get((service_id, instance_id))

    def get_all_offers(self):
        """Get all currently offered services."""
        return list(self._offered_services.values())

    def is_service_offered(self, service_id: int, instance_id: int = 0xFFFF) -> bool:
        """Check if a service is currently offered.

        If instance_id is 0xFFFF, checks if any instance is offered.
        """
        if instance_id == 0xFFFF:
            return any(
                sid == service_id for sid, _ in self._offered_services
            )
        return (service_id, instance_id) in self._offered_services

    def add_subscription(self, service_id: int, instance_id: int,
                         eventgroup_id: int, major_version: int,
                         remote_address: str = "", remote_port: int = 0) -> None:
        """Add or update an eventgroup subscription."""
        key = (service_id, instance_id, eventgroup_id)
        sub = self._subscriptions.get(key)
        if sub:
            sub.reference_count += 1
            sub.is_subscribed = True
        else:
            self._subscriptions[key] = SubscriptionState(
                service_id=service_id,
                instance_id=instance_id,
                eventgroup_id=eventgroup_id,
                major_version=major_version,
                remote_address=remote_address,
                remote_port=remote_port,
                is_subscribed=True,
                reference_count=1,
            )

    def remove_subscription(self, service_id: int, instance_id: int,
                            eventgroup_id: int) -> None:
        """Remove an eventgroup subscription."""
        key = (service_id, instance_id, eventgroup_id)
        sub = self._subscriptions.get(key)
        if sub:
            sub.reference_count -= 1
            if sub.reference_count <= 0:
                del self._subscriptions[key]

    def get_subscription(self, service_id: int, instance_id: int,
                         eventgroup_id: int) -> Optional[SubscriptionState]:
        """Get subscription state for an eventgroup."""
        return self._subscriptions.get((service_id, instance_id, eventgroup_id))

    def get_subscriptions_for_service(self, service_id: int, instance_id: int):
        """Get all subscriptions for a service instance."""
        return [
            sub for key, sub in self._subscriptions.items()
            if key[0] == service_id and key[1] == instance_id
        ]
