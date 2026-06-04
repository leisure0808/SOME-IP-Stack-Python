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
from .header import SdFlags
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

    Args:
        transport: Transport for service messages (events, requests).
        config: Stack configuration with SD parameters.
        sd_transport: Optional separate transport for SD messages.
            If provided, all SD I/O (OfferService, FindService,
            SubscribeEventgroup, ACK/NACK) goes through this transport.
            If not provided, falls back to the main transport.
    """

    def __init__(
        self,
        transport: AbstractTransport,
        config: StackConfiguration,
        sd_transport: Optional[AbstractTransport] = None,
    ):
        self._transport = transport
        self._sd_transport = sd_transport or transport
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
        self._on_eventgroup_nack: Optional[Callable] = None
        self._subscription_validator: Optional[Callable] = None

        # SD timers for each offered service
        self._offer_timers: Dict[tuple, SdTimer] = {}

        # TTL expiry check task
        self._ttl_check_task: Optional[asyncio.Task] = None

        # SD timing configuration (AUTOSAR spec defaults)
        self._sd_timing = SdTimingConfig()

        # Session ID counters (separate for multicast and unicast per spec)
        self._session_id_multicast = 0
        self._session_id_unicast = 0
        self._reboot_flag = True  # Set on startup, cleared after session IDs start

    def set_service_available_handler(self, handler: Callable) -> None:
        """Set callback for when a service becomes available.

        Handler signature: handler(service_id, instance_id, offer: OfferedService)
        """
        self._on_service_available = handler

    def set_service_unavailable_handler(self, handler: Callable) -> None:
        """Set callback for when a service becomes unavailable."""
        self._on_service_unavailable = handler

    def set_eventgroup_subscribed_handler(self, handler: Callable) -> None:
        """Set callback for when an eventgroup subscription is acknowledged.

        Handler signature: handler(service_id, instance_id, eventgroup_id, source)
        where source is (ip, port) of the subscriber.
        """
        self._on_eventgroup_subscribed = handler

    def set_eventgroup_nack_handler(self, handler: Callable) -> None:
        """Set callback for when an eventgroup subscription is rejected (NACK).

        Handler signature: handler(service_id, instance_id, eventgroup_id)
        """
        self._on_eventgroup_nack = handler

    def set_subscription_validator(self, validator: Callable) -> None:
        """Set validator for incoming subscription requests.

        Validator signature: validator(service_id, instance_id, eventgroup_id, source) -> bool
        Returns True to accept (send ACK), False to reject (send NACK).
        """
        self._subscription_validator = validator

    def _next_session_id(self, multicast: bool = True) -> int:
        """Get next SD session ID.

        Per AUTOSAR spec: increments from 0x0001 to 0xFFFF, wraps to 0x0001.
        Separate counters for multicast and unicast.
        """
        if multicast:
            self._session_id_multicast += 1
            if self._session_id_multicast > 0xFFFF:
                self._session_id_multicast = 0x0001
            sid = self._session_id_multicast
        else:
            self._session_id_unicast += 1
            if self._session_id_unicast > 0xFFFF:
                self._session_id_unicast = 0x0001
            sid = self._session_id_unicast

        # Clear reboot flag after session ID starts counting
        if self._reboot_flag:
            self._reboot_flag = False

        return sid

    def _build_sd_message(self, entries, options=None, multicast=True) -> SdMessage:
        """Build an SdMessage with proper session ID and flags."""
        session_id = self._next_session_id(multicast)
        flags = SdFlags(
            reboot_flag=self._reboot_flag,
            unicast_flag=True,
        )
        return SdMessage(
            flags=flags,
            entries=entries,
            options=options or [],
            session_id=session_id,
        )

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

    async def stop_subscribe_eventgroup(
        self,
        service_id: int,
        instance_id: int,
        eventgroup_id: int,
        major_version: int,
    ) -> None:
        """Stop subscribing to an eventgroup (sends StopSubscribeEventgroup)."""
        await self._send_stop_subscribe(service_id, instance_id, eventgroup_id, major_version)
        logger.info(
            "Stopped subscribing to eventgroup %d of service 0x%04X instance 0x%04X",
            eventgroup_id, service_id, instance_id,
        )

    async def stop(self) -> None:
        """Stop the SD agent and all timers."""
        for timer in self._offer_timers.values():
            await timer.stop()
        self._offer_timers.clear()

        if self._ttl_check_task and not self._ttl_check_task.done():
            self._ttl_check_task.cancel()
            try:
                await self._ttl_check_task
            except asyncio.CancelledError:
                pass
            self._ttl_check_task = None

    async def start_sd_listener(self) -> None:
        """Start listening for SD messages on the SD transport.

        Registers the SD message handler on the SD transport and joins
        the SD multicast group. Call this after the SD transport has been
        started. If multicast group join fails, logs a warning and
        continues (unicast SD still works).
        """
        self._sd_transport.set_message_handler(self._on_message_received)

        # Try to join multicast group if the SD transport is a UdpTransport
        from ..transport.udp import UdpTransport
        if isinstance(self._sd_transport, UdpTransport):
            try:
                self._sd_transport.join_multicast_group(
                    self._config.sd_multicast_address,
                    self._config.unicast_address,
                )
            except OSError as e:
                logger.warning(
                    "Failed to join multicast group %s (multicast may not work): %s",
                    self._config.sd_multicast_address, e,
                )

    async def start_ttl_check(self) -> None:
        """Start periodic TTL expiry checking."""
        if self._ttl_check_task is None or self._ttl_check_task.done():
            self._ttl_check_task = asyncio.create_task(self._ttl_check_loop())

    async def _ttl_check_loop(self) -> None:
        """Periodically check for expired offers and subscriptions."""
        try:
            while True:
                await asyncio.sleep(1.0)

                # Check expired offers
                expired_offers = self._subscription_mgr.check_expired_offers()
                for service_id, instance_id in expired_offers:
                    logger.info("TTL expired for service 0x%04X instance 0x%04X", service_id, instance_id)
                    if self._on_service_unavailable:
                        self._on_service_unavailable(service_id, instance_id)

                # Check expired subscriptions
                expired_subs = self._subscription_mgr.check_expired_subscriptions()
                for service_id, instance_id, eventgroup_id in expired_subs:
                    logger.info("TTL expired for subscription eventgroup %d of 0x%04X", eventgroup_id, service_id)
                    if self._on_eventgroup_unsubscribed:
                        self._on_eventgroup_unsubscribed(service_id, instance_id, eventgroup_id)
        except asyncio.CancelledError:
            pass

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
                    self._handle_subscribe(entry, sd_msg.options, source)
                else:
                    self._handle_stop_subscribe(entry)

            elif entry.entry_type == SdEntryType.SUBSCRIBE_EVENTGROUP_ACK:
                if entry.ttl > 0:
                    self._handle_subscribe_ack(entry)
                else:
                    # TTL=0 means NACK
                    self._handle_subscribe_nack(entry)

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
        if not offer:
            # Look for any matching instance
            for (sid, iid), o in self._offers.items():
                if sid == entry.service_id:
                    # Match if: exact instance, or finder asks for any (0xFFFF)
                    if iid == entry.instance_id or entry.instance_id == 0xFFFF:
                        offer = o
                        break

        if offer:
            # Send a unicast OfferService directly to the finder
            asyncio.ensure_future(self._send_offer_to(offer, source))

            # Also force offer timer to main phase to trigger next cyclic offer sooner
            for k, timer in self._offer_timers.items():
                if k[0] == entry.service_id:
                    timer.force_main_phase()

    def _handle_subscribe(self, entry: SdEntry, options: list, source: tuple) -> None:
        """Handle a SubscribeEventgroup entry."""
        # Determine subscriber's unicast endpoint for event delivery.
        # Per AUTOSAR spec, the subscriber includes an IPv4 Endpoint Option
        # indicating where events should be sent. If no endpoint option is
        # present, fall back to the SD message source address/port.
        subscriber_addr = None
        for opt in options:
            if isinstance(opt, IPv4EndpointOption) and opt.port > 0:
                subscriber_addr = (opt.address, opt.port)
                break

        if subscriber_addr is None:
            # No endpoint option — use SD source (may be SD port, not ideal)
            subscriber_addr = (source[0] if source else "", source[1] if source else 0)
            logger.debug(
                "No endpoint option in SubscribeEventgroup, using source %s", subscriber_addr
            )

        # Check subscription validator if configured
        if self._subscription_validator:
            try:
                accepted = self._subscription_validator(
                    entry.service_id, entry.instance_id,
                    entry.eventgroup_id, subscriber_addr,
                )
            except Exception:
                accepted = False

            if not accepted:
                # Send NACK (type=0x07, TTL=0)
                asyncio.ensure_future(
                    self._send_subscribe_nack(entry, source)
                )
                return

        self._subscription_mgr.add_subscription(
            entry.service_id, entry.instance_id,
            entry.eventgroup_id, entry.major_version,
            subscriber_addr[0], subscriber_addr[1],
        )

        if self._on_eventgroup_subscribed:
            self._on_eventgroup_subscribed(
                entry.service_id, entry.instance_id,
                entry.eventgroup_id, subscriber_addr,
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
        """Handle a SubscribeEventgroupAck (type=0x07, TTL>0)."""
        logger.info(
            "Subscribe ACK for eventgroup %d of service 0x%04X",
            entry.eventgroup_id, entry.service_id,
        )

    def _handle_subscribe_nack(self, entry: SdEntry) -> None:
        """Handle a SubscribeEventgroupNACK (type=0x07, TTL=0)."""
        logger.warning(
            "Subscribe NACK for eventgroup %d of service 0x%04X",
            entry.eventgroup_id, entry.service_id,
        )
        if self._on_eventgroup_nack:
            self._on_eventgroup_nack(
                entry.service_id, entry.instance_id,
                entry.eventgroup_id,
            )

    async def _send_offer(self, offer: ServiceOffer) -> None:
        """Send an OfferService SD message (multicast)."""
        await self._send_offer_to(offer, None)

    async def _send_offer_to(self, offer: ServiceOffer, target: tuple) -> None:
        """Send an OfferService SD message to a specific target (unicast) or multicast."""
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

        is_multicast = target is None
        sd_msg = self._build_sd_message([entry], options, multicast=is_multicast)
        data = sd_msg.serialize()
        msg = SomeipMessage.deserialize(data)
        endpoint = target if target else (self._config.sd_multicast_address, self._config.sd_port)
        try:
            await self._sd_transport.send(msg, endpoint)
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

        sd_msg = self._build_sd_message([entry], multicast=True)
        data = sd_msg.serialize()
        msg = SomeipMessage.deserialize(data)
        endpoint = (self._config.sd_multicast_address, self._config.sd_port)
        try:
            await self._sd_transport.send(msg, endpoint)
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

        sd_msg = self._build_sd_message([entry], multicast=True)
        data = sd_msg.serialize()
        msg = SomeipMessage.deserialize(data)

        # Send to multicast address
        multicast_endpoint = (self._config.sd_multicast_address, self._config.sd_port)
        try:
            await self._sd_transport.send(msg, multicast_endpoint)
        except Exception as e:
            logger.warning("Failed to send FindService (multicast): %s", e)

        # Also send unicast to local SD port for localhost discovery.
        # Multicast may not be routable on some systems (especially Windows loopback),
        # so unicast fallback ensures FindService reaches a local server.
        unicast_endpoint = (self._config.unicast_address, self._config.sd_port)
        if unicast_endpoint != multicast_endpoint:
            try:
                await self._sd_transport.send(msg, unicast_endpoint)
            except Exception as e:
                logger.debug("Failed to send FindService (unicast): %s", e)

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

        # Build endpoint option so the server knows where to send events.
        # Uses the main transport's port (service port), not the SD transport's port.
        options = []
        from ..transport.udp import UdpTransport
        if isinstance(self._transport, UdpTransport) and self._transport.is_running:
            options.append(IPv4EndpointOption(
                option_type=SdOptionType.IPv4_ENDPOINT,
                address=self._config.unicast_address,
                port=self._transport.local_port,
                protocol=17,
            ))

        sd_msg = self._build_sd_message([entry], options, multicast=True)
        data = sd_msg.serialize()
        msg = SomeipMessage.deserialize(data)

        # Send to multicast address
        multicast_endpoint = (self._config.sd_multicast_address, self._config.sd_port)
        try:
            await self._sd_transport.send(msg, multicast_endpoint)
        except Exception as e:
            logger.warning("Failed to send SubscribeEventgroup (multicast): %s", e)

        # Also send unicast to local SD port (same reason as FindService)
        unicast_endpoint = (self._config.unicast_address, self._config.sd_port)
        if unicast_endpoint != multicast_endpoint:
            try:
                await self._sd_transport.send(msg, unicast_endpoint)
            except Exception as e:
                logger.debug("Failed to send SubscribeEventgroup (unicast): %s", e)

    async def _send_stop_subscribe(
        self, service_id: int, instance_id: int,
        eventgroup_id: int, major_version: int,
    ) -> None:
        """Send a StopSubscribeEventgroup SD message (type=0x06, TTL=0)."""
        entry = SdEntry(
            entry_type=SdEntryType.SUBSCRIBE_EVENTGROUP,  # Same type as subscribe
            service_id=service_id,
            instance_id=instance_id,
            major_version=major_version,
            ttl=0,  # TTL=0 means Stop
            eventgroup_id=eventgroup_id,
        )

        sd_msg = self._build_sd_message([entry], multicast=True)
        data = sd_msg.serialize()
        msg = SomeipMessage.deserialize(data)

        multicast_endpoint = (self._config.sd_multicast_address, self._config.sd_port)
        try:
            await self._sd_transport.send(msg, multicast_endpoint)
        except Exception as e:
            logger.warning("Failed to send StopSubscribeEventgroup (multicast): %s", e)

        unicast_endpoint = (self._config.unicast_address, self._config.sd_port)
        if unicast_endpoint != multicast_endpoint:
            try:
                await self._sd_transport.send(msg, unicast_endpoint)
            except Exception as e:
                logger.debug("Failed to send StopSubscribeEventgroup (unicast): %s", e)

    async def _send_subscribe_ack(self, original_entry: SdEntry, source: tuple) -> None:
        """Send a SubscribeEventgroupAck SD message (type=0x07, TTL>0)."""
        entry = SdEntry(
            entry_type=SdEntryType.SUBSCRIBE_EVENTGROUP_ACK,
            service_id=original_entry.service_id,
            instance_id=original_entry.instance_id,
            major_version=original_entry.major_version,
            ttl=0xFFFFFF,
            eventgroup_id=original_entry.eventgroup_id,
        )

        sd_msg = self._build_sd_message([entry], multicast=False)
        data = sd_msg.serialize()
        msg = SomeipMessage.deserialize(data)
        try:
            await self._sd_transport.send(msg, source)
        except Exception as e:
            logger.warning("Failed to send SubscribeEventgroupAck: %s", e)

    async def _send_subscribe_nack(self, original_entry: SdEntry, source: tuple) -> None:
        """Send a SubscribeEventgroupNACK SD message (type=0x07, TTL=0)."""
        entry = SdEntry(
            entry_type=SdEntryType.SUBSCRIBE_EVENTGROUP_ACK,  # Same type as ACK
            service_id=original_entry.service_id,
            instance_id=original_entry.instance_id,
            major_version=original_entry.major_version,
            ttl=0,  # TTL=0 means NACK
            eventgroup_id=original_entry.eventgroup_id,
        )

        sd_msg = self._build_sd_message([entry], multicast=False)
        data = sd_msg.serialize()
        msg = SomeipMessage.deserialize(data)
        try:
            await self._sd_transport.send(msg, source)
        except Exception as e:
            logger.warning("Failed to send SubscribeEventgroupNACK: %s", e)
