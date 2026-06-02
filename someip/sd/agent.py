"""SOME/IP Service Discovery Agent.

SdAgent manages the full SD lifecycle:
- Offering services (OfferService/StopOfferService)
- Finding services (FindService)
- Subscribing to eventgroups (SubscribeEventgroup/StopSubscribeEventgroup)
- Processing incoming SD messages
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set

from ..config.stack_config import StackConfiguration
from ..message.message import SomeipMessage
from ..transport.base import AbstractTransport
from .entry import SdEntry, SdEntryType
from .message import SdMessage
from .option import IPv4EndpointOption, SdOptionType
from .subscription import SubscriptionManager, OfferedService
from .timer import SdTimer, SdTimingConfig

logger = logging.getLogger(__name__)


@dataclass
class ServiceOffer:
    """A service being offered by this agent."""

    service_id: int
    instance_id: int
    major_version: int
    minor_version: int
    ttl: int = 0xFFFFFF  # 3 bytes max
    address: str = "0.0.0.0"
    port: int = 0
    protocol: int = 17  # UDP
    eventgroups: Set[int] = None

    def __post_init__(self):
        if self.eventgroups is None:
            self.eventgroups = set()


@dataclass
class ServiceFind:
    """A service being searched for by this agent."""

    service_id: int
    instance_id: int  # 0xFFFF = any instance
    major_version: int = 0xFF  # 0xFF = any version
    eventgroups: Set[int] = None

    def __post_init__(self):
        if self.eventgroups is None:
            self.eventgroups = set()


class SdAgent:
    """SOME/IP Service Discovery Agent.

    Manages service offers, finds, and eventgroup subscriptions.
    Communicates via a transport layer using SD multicast/unicast.
    """

    def __init__(
        self,
        transport: AbstractTransport,
        config: StackConfiguration,
    ):
        self._transport = transport
        self._config = config
        self._subscription_mgr = SubscriptionManager()

        # Services we offer
        self._offers: Dict[tuple, ServiceOffer] = {}
        # Services we're looking for
        self._finds: Dict[tuple, ServiceFind] = {}

        # Callbacks
        self._on_service_available: Optional[Callable] = None
        self._on_service_unavailable: Optional[Callable] = None
        self._on_eventgroup_subscribed: Optional[Callable] = None
        self._on_eventgroup_unsubscribed: Optional[Callable] = None

        # SD timers for each offered service
        self._offer_timers: Dict[tuple, SdTimer] = {}

        # SD timing configuration
        self._sd_timing = SdTimingConfig(
            initial_delay_min=0.0,
            initial_delay_max=0.5,
            repetitions_base_delay=0.01,
            repetitions_max=3,
            cyclic_offer_delay=2.0,
        )

        # Session ID counter
        self._session_id = 0

        # Set transport message handler
        self._transport.set_message_handler(self._on_message_received)

    def set_service_available_handler(self, handler: Callable) -> None:
        """Set callback for when a service becomes available.

        Handler signature: handler(service_id, instance_id, offer: OfferedService)
        """
        self._on_service_available = handler

    def set_service_unavailable_handler(self, handler: Callable) -> None:
        """Set callback for when a service becomes unavailable."""
        self._on_service_unavailable = handler

    def set_eventgroup_subscribed_handler(self, handler: Callable) -> None:
        """Set callback for when an eventgroup subscription is acknowledged."""
        self._on_eventgroup_subscribed = handler

    async def offer_service(self, offer: ServiceOffer) -> None:
        """Start offering a service."""
        key = (offer.service_id, offer.instance_id)
        self._offers[key] = offer

        # Start SD timer for this offer
        timer = SdTimer(
            config=self._sd_timing,
            callback=lambda: asyncio.ensure_future(
                self._send_offer(offer)
            ),
            name=f"offer-{offer.service_id:#x}-{offer.instance_id:#x}",
        )
        self._offer_timers[key] = timer
        await timer.start()

        logger.info(
            "Offering service 0x%04X instance 0x%04X",
            offer.service_id, offer.instance_id,
        )

    async def stop_offer_service(self, service_id: int, instance_id: int) -> None:
        """Stop offering a service."""
        key = (service_id, instance_id)
        offer = self._offers.pop(key, None)
        if offer:
            # Stop timer
            timer = self._offer_timers.pop(key, None)
            if timer:
                await timer.stop()

            # Send StopOffer (TTL=0)
            await self._send_stop_offer(offer)

        logger.info(
            "Stopped offering service 0x%04X instance 0x%04X",
            service_id, instance_id,
        )

    async def find_service(
        self,
        service_id: int,
        instance_id: int = 0xFFFF,
        major_version: int = 0xFF,
    ) -> None:
        """Search for a service."""
        key = (service_id, instance_id)
        find = ServiceFind(
            service_id=service_id,
            instance_id=instance_id,
            major_version=major_version,
        )
        self._finds[key] = find

        # Send FindService
        await self._send_find(find)

        logger.info(
            "Finding service 0x%04X instance 0x%04X",
            service_id, instance_id,
        )

    async def subscribe_eventgroup(
        self,
        service_id: int,
        instance_id: int,
        eventgroup_id: int,
        major_version: int,
    ) -> None:
        """Subscribe to an eventgroup."""
        offer = self._subscription_mgr.get_offered_service(service_id, instance_id)
        if not offer:
            logger.warning(
                "Cannot subscribe to eventgroup %d: service 0x%04X instance 0x%04X not offered",
                eventgroup_id, service_id, instance_id,
            )
            return

        await self._send_subscribe(service_id, instance_id, eventgroup_id, major_version)
        logger.info(
            "Subscribed to eventgroup %d of service 0x%04X instance 0x%04X",
            eventgroup_id, service_id, instance_id,
        )

    async def stop(self) -> None:
        """Stop the SD agent and all timers."""
        for timer in self._offer_timers.values():
            await timer.stop()
        self._offer_timers.clear()

    def _on_message_received(self, message: SomeipMessage, source: tuple) -> None:
        """Handle incoming SOME/IP messages (looking for SD messages)."""
        if not message.header.is_sd:
            return

        try:
            sd_msg = SdMessage.deserialize_from_message(message)
        except Exception as e:
            logger.warning("Failed to parse SD message: %s", e)
            return

        self._process_sd_message(sd_msg, source)

    def _process_sd_message(self, sd_msg: SdMessage, source: tuple) -> None:
        """Process a received SD message."""
        for entry in sd_msg.entries:
            if entry.entry_type == SdEntryType.OFFER_SERVICE:
                if entry.ttl > 0:
                    self._handle_offer(entry, sd_msg.options, source)
                else:
                    self._handle_stop_offer(entry)

            elif entry.entry_type == SdEntryType.FIND_SERVICE:
                self._handle_find(entry, source)

            elif entry.entry_type == SdEntryType.SUBSCRIBE_EVENTGROUP:
                if entry.ttl > 0:
                    self._handle_subscribe(entry, source)
                else:
                    self._handle_stop_subscribe(entry)

            elif entry.entry_type in (
                SdEntryType.SUBSCRIBE_EVENTGROUP_ACK,
                SdEntryType.SUBSCRIBE_EVENTGROUP_NACK,
            ):
                self._handle_subscribe_ack(entry)

    def _handle_offer(self, entry: SdEntry, options: list, source: tuple) -> None:
        """Handle an OfferService entry."""
        self._subscription_mgr.update_offer(entry)

        # Extract endpoint from options
        for option in options:
            if isinstance(option, IPv4EndpointOption):
                self._subscription_mgr.update_offer_endpoint(
                    entry.service_id, entry.instance_id,
                    option.address, option.port, option.protocol,
                )

        offer = self._subscription_mgr.get_offered_service(
            entry.service_id, entry.instance_id
        )
        if offer and self._on_service_available:
            self._on_service_available(
                entry.service_id, entry.instance_id, offer
            )

        # If we're looking for this service, no longer need to find
        key = (entry.service_id, entry.instance_id)
        if key in self._finds:
            del self._finds[key]
        # Also check for "any instance" finds
        any_key = (entry.service_id, 0xFFFF)
        if any_key in self._finds:
            if self._on_service_available:
                self._on_service_available(
                    entry.service_id, entry.instance_id, offer
                )

    def _handle_stop_offer(self, entry: SdEntry) -> None:
        """Handle a StopOfferService entry (TTL=0)."""
        offer = self._subscription_mgr.get_offered_service(
            entry.service_id, entry.instance_id
        )
        self._subscription_mgr.update_offer(entry)  # TTL=0 removes it

        if offer and self._on_service_unavailable:
            self._on_service_unavailable(
                entry.service_id, entry.instance_id
            )

    def _handle_find(self, entry: SdEntry, source: tuple) -> None:
        """Handle a FindService entry."""
        # Check if we offer the requested service
        key = (entry.service_id, entry.instance_id)
        offer = self._offers.get(key)
        if not offer and entry.instance_id != 0xFFFF:
            # Check for any instance
            for (sid, iid), o in self._offers.items():
                if sid == entry.service_id:
                    offer = o
                    break

        if offer:
            # Force offer timer to main phase to respond quickly
            timer = self._offer_timers.get(key)
            if timer:
                timer.force_main_phase()

    def _handle_subscribe(self, entry: SdEntry, source: tuple) -> None:
        """Handle a SubscribeEventgroup entry."""
        self._subscription_mgr.add_subscription(
            entry.service_id, entry.instance_id,
            entry.eventgroup_id, entry.major_version,
            source[0] if source else "", source[1] if source else 0,
        )

        if self._on_eventgroup_subscribed:
            self._on_eventgroup_subscribed(
                entry.service_id, entry.instance_id,
                entry.eventgroup_id,
            )

        # Send ACK
        asyncio.ensure_future(
            self._send_subscribe_ack(entry, source)
        )

    def _handle_stop_subscribe(self, entry: SdEntry) -> None:
        """Handle a StopSubscribeEventgroup entry."""
        self._subscription_mgr.remove_subscription(
            entry.service_id, entry.instance_id,
            entry.eventgroup_id,
        )

        if self._on_eventgroup_unsubscribed:
            self._on_eventgroup_unsubscribed(
                entry.service_id, entry.instance_id,
                entry.eventgroup_id,
            )

    def _handle_subscribe_ack(self, entry: SdEntry) -> None:
        """Handle a SubscribeEventgroupAck/Nack."""
        if entry.entry_type == SdEntryType.SUBSCRIBE_EVENTGROUP_ACK:
            logger.info(
                "Subscribe ACK for eventgroup %d of service 0x%04X",
                entry.eventgroup_id, entry.service_id,
            )
        else:
            logger.warning(
                "Subscribe NACK for eventgroup %d of service 0x%04X",
                entry.eventgroup_id, entry.service_id,
            )

    async def _send_offer(self, offer: ServiceOffer) -> None:
        """Send an OfferService SD message."""
        entry = SdEntry(
            entry_type=SdEntryType.OFFER_SERVICE,
            service_id=offer.service_id,
            instance_id=offer.instance_id,
            major_version=offer.major_version,
            ttl=offer.ttl,
            minor_version=offer.minor_version,
        )

        # Build endpoint option if address is set
        options = []
        if offer.address != "0.0.0.0":
            opt = IPv4EndpointOption(
                option_type=SdOptionType.IPv4_ENDPOINT,
                address=offer.address,
                port=offer.port,
                protocol=offer.protocol,
            )
            options.append(opt)

        sd_msg = SdMessage(entries=[entry], options=options)
        data = sd_msg.serialize()

        # Send as SOME/IP message via transport
        msg = SomeipMessage.deserialize(data)
        endpoint = (self._config.sd_multicast_address, self._config.sd_port)
        try:
            await self._transport.send(msg, endpoint)
        except Exception as e:
            logger.warning("Failed to send OfferService: %s", e)

    async def _send_stop_offer(self, offer: ServiceOffer) -> None:
        """Send a StopOfferService SD message (TTL=0)."""
        entry = SdEntry(
            entry_type=SdEntryType.OFFER_SERVICE,
            service_id=offer.service_id,
            instance_id=offer.instance_id,
            major_version=offer.major_version,
            ttl=0,
            minor_version=offer.minor_version,
        )

        sd_msg = SdMessage(entries=[entry])
        data = sd_msg.serialize()
        msg = SomeipMessage.deserialize(data)
        endpoint = (self._config.sd_multicast_address, self._config.sd_port)
        try:
            await self._transport.send(msg, endpoint)
        except Exception as e:
            logger.warning("Failed to send StopOfferService: %s", e)

    async def _send_find(self, find: ServiceFind) -> None:
        """Send a FindService SD message."""
        entry = SdEntry(
            entry_type=SdEntryType.FIND_SERVICE,
            service_id=find.service_id,
            instance_id=find.instance_id,
            major_version=find.major_version,
            ttl=0xFFFFFF,
        )

        sd_msg = SdMessage(entries=[entry])
        data = sd_msg.serialize()
        msg = SomeipMessage.deserialize(data)
        endpoint = (self._config.sd_multicast_address, self._config.sd_port)
        try:
            await self._transport.send(msg, endpoint)
        except Exception as e:
            logger.warning("Failed to send FindService: %s", e)

    async def _send_subscribe(
        self, service_id: int, instance_id: int,
        eventgroup_id: int, major_version: int,
    ) -> None:
        """Send a SubscribeEventgroup SD message."""
        entry = SdEntry(
            entry_type=SdEntryType.SUBSCRIBE_EVENTGROUP,
            service_id=service_id,
            instance_id=instance_id,
            major_version=major_version,
            ttl=0xFFFFFF,
            eventgroup_id=eventgroup_id,
        )

        sd_msg = SdMessage(entries=[entry])
        data = sd_msg.serialize()
        msg = SomeipMessage.deserialize(data)
        endpoint = (self._config.sd_multicast_address, self._config.sd_port)
        try:
            await self._transport.send(msg, endpoint)
        except Exception as e:
            logger.warning("Failed to send SubscribeEventgroup: %s", e)

    async def _send_subscribe_ack(self, original_entry: SdEntry, source: tuple) -> None:
        """Send a SubscribeEventgroupAck SD message."""
        entry = SdEntry(
            entry_type=SdEntryType.SUBSCRIBE_EVENTGROUP_ACK,
            service_id=original_entry.service_id,
            instance_id=original_entry.instance_id,
            major_version=original_entry.major_version,
            ttl=0xFFFFFF,
            eventgroup_id=original_entry.eventgroup_id,
        )

        sd_msg = SdMessage(entries=[entry])
        data = sd_msg.serialize()
        msg = SomeipMessage.deserialize(data)
        # Send unicast to the subscriber
        try:
            await self._transport.send(msg, source)
        except Exception as e:
            logger.warning("Failed to send SubscribeEventgroupAck: %s", e)
