"""SOME/IP Event Subscription Example.

Demonstrates event publishing and subscribing via SD protocol:
- Server: offers a service via SD, publishes periodic events to subscribers
- Client: finds the service via SD, subscribes to eventgroup, receives notifications

Uses standard SOME/IP Service Discovery (SubscribeEventgroup/ACK)
with separate transports for SD and service messages.

Architecture:
- SD transport: bound on SD port (30490), handles OfferService, FindService,
  SubscribeEventgroup, ACK/NACK via multicast/unicast
- Service transport: bound on server port (30502) or ephemeral port, handles
  event notifications and service messages

Run in two terminals:
  Terminal 1: python -m examples.event_subscription server
  Terminal 2: python -m examples.event_subscription client
"""

import asyncio
import logging
import struct
import sys
import time

from someip.config.service_config import ServiceInterfaceConfig
from someip.config.stack_config import StackConfiguration
from someip.message.message import SomeipMessage
from someip.sd.agent import SdAgent, ServiceOffer
from someip.service.skeleton import Skeleton
from someip.service.proxy import Proxy
from someip.service.dispatcher import Dispatcher
from someip.transport.udp import UdpTransport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("event_subscription")

# Service definition
SERVICE_ID = 0x5001
INSTANCE_ID = 0x0001
MAJOR_VERSION = 1
MINOR_VERSION = 0
EVENT_TEMPERATURE = 0x8001  # Event IDs have bit 15 set
EVENT_STATUS = 0x8002
EVENTGROUP_ID = 0x0001
SERVER_PORT = 30502
SD_PORT = 30490

SD_MULTICAST = "224.224.224.245"

FAIL_THRESHOLD = 3
SUBSCRIBER_TTL = 30  # seconds: remove if no re-subscribe within this time


async def run_server():
    """Start a server that offers its service and publishes events via SD."""
    config = ServiceInterfaceConfig(
        service_id=SERVICE_ID,
        instance_id=INSTANCE_ID,
        interface_version=MAJOR_VERSION,
    )

    skeleton = Skeleton(config)

    # Register events
    temp_event = skeleton.register_event(EVENT_TEMPERATURE)
    status_event = skeleton.register_event(EVENT_STATUS)

    # Register eventgroup
    eventgroup = skeleton.register_eventgroup(EVENTGROUP_ID)
    eventgroup.add_event(EVENT_TEMPERATURE)
    eventgroup.add_event(EVENT_STATUS)

    # Service transport for SOME/IP messages (events, requests)
    transport = UdpTransport(local_port=SERVER_PORT)
    dispatcher = Dispatcher()
    dispatcher.register_skeleton(skeleton)

    # SD transport on the SD port for SD messages
    sd_transport = UdpTransport(local_port=SD_PORT)

    # Stack configuration
    stack_config = StackConfiguration(
        unicast_address="127.0.0.1",
        sd_multicast_address=SD_MULTICAST,
        sd_port=SD_PORT,
    )

    # Track subscribers: (address, port) -> (fail_count, last_sub_time)
    subscribers = {}

    # SdAgent with separate SD transport
    sd_agent = SdAgent(transport, stack_config, sd_transport=sd_transport)

    # When a client subscribes to our eventgroup via SD, track them
    def on_eventgroup_subscribed(service_id, instance_id, eventgroup_id, source):
        subscribers[source] = (0, time.monotonic())
        logger.info("Client subscribed to eventgroup %d from %s", eventgroup_id, source)

    sd_agent.set_eventgroup_subscribed_handler(on_eventgroup_subscribed)

    # Service message routing (on service transport)
    async def on_service_message(message: SomeipMessage, source: tuple):
        if message.header.is_sd:
            sd_agent._on_message_received(message, source)
        else:
            response = await dispatcher.dispatch(message, source)
            if response is not None:
                await transport.send(response, source)

    transport.set_message_handler(on_service_message)

    # Start both transports
    await transport.start()
    await sd_transport.start()

    # Register SD handler + join multicast group on SD transport
    await sd_agent.start_sd_listener()

    # Offer the service via SdAgent (handles periodic OfferService + FindService responses)
    offer = ServiceOffer(
        service_id=SERVICE_ID,
        instance_id=INSTANCE_ID,
        major_version=MAJOR_VERSION,
        minor_version=MINOR_VERSION,
        ttl=0xFFFFFF,
        address="127.0.0.1",
        port=SERVER_PORT,
        protocol=17,
        eventgroups={EVENTGROUP_ID},
    )
    await sd_agent.offer_service(offer)

    logger.info("Event server started on port %d, SD port %d", SERVER_PORT, SD_PORT)

    # Publish events periodically to all subscribers
    async def publish_events():
        temperature = 20.0
        counter = 0
        while True:
            await asyncio.sleep(1.0)

            temperature += 0.5 * (1 if counter % 3 == 0 else -1)
            counter += 1

            # Temperature event
            temp_payload = struct.pack(">f", temperature)
            temp_msg = SomeipMessage.build_notification(
                service_id=SERVICE_ID,
                event_id=EVENT_TEMPERATURE,
                client_id=0,
                session_id=counter & 0xFFFF,
                interface_version=MAJOR_VERSION,
                payload=temp_payload,
            )

            # Status event
            status = 0x01 if temperature < 25.0 else 0x02
            status_payload = struct.pack(">B", status)
            status_msg = SomeipMessage.build_notification(
                service_id=SERVICE_ID,
                event_id=EVENT_STATUS,
                client_id=0,
                session_id=counter & 0xFFFF,
                interface_version=MAJOR_VERSION,
                payload=status_payload,
            )

            # Send to all subscribers, clean up stale/expired ones
            now = time.monotonic()
            stale = []
            for client_addr, (fail_count, last_sub_time) in list(subscribers.items()):
                if now - last_sub_time > SUBSCRIBER_TTL:
                    stale.append(client_addr)
                    logger.info("Removing expired subscriber %s", client_addr)
                    continue
                try:
                    await transport.send(temp_msg, client_addr)
                    await transport.send(status_msg, client_addr)
                    # Reset fail count on success, keep last_sub_time unchanged
                    subscribers[client_addr] = (0, last_sub_time)
                except OSError:
                    new_count = fail_count + 1
                    if new_count >= FAIL_THRESHOLD:
                        stale.append(client_addr)
                        logger.info("Removing stale subscriber %s after %d failures",
                                    client_addr, new_count)
                    else:
                        subscribers[client_addr] = (new_count, last_sub_time)
            for addr in stale:
                del subscribers[addr]

            logger.info(
                "Published: temp=%.1f, status=%d, subscribers=%d",
                temperature, status, len(subscribers),
            )

    # Run event loop
    try:
        await publish_events()
    except asyncio.CancelledError:
        pass
    finally:
        await sd_agent.stop()
        await sd_transport.stop()
        await transport.stop()


async def run_client():
    """Start a client that discovers a service and subscribes to events via SD."""
    config = ServiceInterfaceConfig(
        service_id=SERVICE_ID,
        instance_id=INSTANCE_ID,
        interface_version=MAJOR_VERSION,
    )

    proxy = Proxy(config)
    proxy.client_id = 0x0002

    # Service transport for SOME/IP messages (events)
    transport = UdpTransport(local_port=0)
    dispatcher = Dispatcher()
    dispatcher.register_proxy(proxy)

    received_events = []

    # Register notification handlers
    def on_temperature(message: SomeipMessage, source: tuple):
        temp = struct.unpack(">f", message.payload)[0]
        logger.info("Temperature event: %.1f C", temp)
        received_events.append(("temperature", temp))

    def on_status(message: SomeipMessage, source: tuple):
        status = message.payload[0]
        status_name = "NORMAL" if status == 0x01 else "WARNING"
        logger.info("Status event: %s (0x%02X)", status_name, status)
        received_events.append(("status", status))

    dispatcher.register_notification_handler(SERVICE_ID, EVENT_TEMPERATURE, on_temperature)
    dispatcher.register_notification_handler(SERVICE_ID, EVENT_STATUS, on_status)

    # SD transport for SD messages (FindService, SubscribeEventgroup, etc.)
    sd_transport = UdpTransport(local_port=0)

    # Stack configuration
    stack_config = StackConfiguration(
        unicast_address="127.0.0.1",
        sd_multicast_address=SD_MULTICAST,
        sd_port=SD_PORT,
    )
    sd_agent = SdAgent(transport, stack_config, sd_transport=sd_transport)

    service_discovered = asyncio.Event()
    offer_info = {}

    def on_service_available(service_id, instance_id, offer):
        logger.info(
            "Service DISCOVERED: 0x%04X instance 0x%04X at %s:%d",
            service_id, instance_id, offer.address, offer.port,
        )
        offer_info["offer"] = offer
        service_discovered.set()

    sd_agent.set_service_available_handler(on_service_available)

    # Service message routing (on service transport)
    async def on_service_message(message: SomeipMessage, source: tuple):
        if message.header.is_sd:
            sd_agent._on_message_received(message, source)
        else:
            await dispatcher.dispatch(message, source)

    transport.set_message_handler(on_service_message)

    # Start both transports
    await transport.start()
    await sd_transport.start()

    # Register SD handler + join multicast group on SD transport
    await sd_agent.start_sd_listener()

    logger.info("Event client started, looking for service 0x%04X ...", SERVICE_ID)

    # Step 1: Find the service via SdAgent
    await sd_agent.find_service(SERVICE_ID, INSTANCE_ID, MAJOR_VERSION)

    # Also send FindService as unicast to the server's SD port for faster discovery
    await sd_agent.find_service(SERVICE_ID, 0xFFFF, 0xFF)

    # Wait for service discovery (server will unicast OfferService back)
    try:
        await asyncio.wait_for(service_discovered.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning("Service not discovered after 10s, make sure server is running")
        await sd_agent.stop()
        await sd_transport.stop()
        await transport.stop()
        return

    # Step 2: Subscribe to the eventgroup via SdAgent
    offer = offer_info.get("offer")
    server_sd_endpoint = (offer.address, SD_PORT) if offer else ("127.0.0.1", SD_PORT)

    await sd_agent.subscribe_eventgroup(
        SERVICE_ID, INSTANCE_ID, EVENTGROUP_ID, MAJOR_VERSION,
    )
    logger.info("SubscribeEventgroup(%d) sent", EVENTGROUP_ID)

    logger.info("Listening for events from service 0x%04X ...", SERVICE_ID)

    try:
        for i in range(15):
            await asyncio.sleep(1.0)
            # Re-subscribe every 5s to keep subscription alive
            if i > 0 and i % 5 == 0:
                await sd_agent.subscribe_eventgroup(
                    SERVICE_ID, INSTANCE_ID, EVENTGROUP_ID, MAJOR_VERSION,
                )
                logger.debug("Re-sent SubscribeEventgroup")

        logger.info("Received %d events total", len(received_events))

    except asyncio.CancelledError:
        pass
    finally:
        await sd_agent.stop()
        await sd_transport.stop()
        await transport.stop()
        logger.info("Client stopped")


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m examples.event_subscription [server|client]")
        sys.exit(1)

    mode = sys.argv[1].lower()
    if mode == "server":
        asyncio.run(run_server())
    elif mode == "client":
        asyncio.run(run_client())
    else:
        print(f"Unknown mode: {mode}. Use 'server' or 'client'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
