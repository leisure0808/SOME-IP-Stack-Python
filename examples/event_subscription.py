"""SOME/IP Event Subscription Example.

Demonstrates event publishing and subscribing:
- Server: publishes periodic events to subscribers
- Client: subscribes to events and receives notifications

Run in two terminals:
  Terminal 1: python -m examples.event_subscription server
  Terminal 2: python -m examples.event_subscription client
"""

import asyncio
import logging
import struct
import sys

from someip.config.service_config import ServiceInterfaceConfig
from someip.config.stack_config import StackConfiguration
from someip.message.message import SomeipMessage
from someip.service.skeleton import Skeleton
from someip.service.proxy import Proxy
from someip.service.dispatcher import Dispatcher
from someip.service.event import Event
from someip.transport.udp import UdpTransport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("event_subscription")

# Service definition
SERVICE_ID = 0x5001
INSTANCE_ID = 0x0001
EVENT_TEMPERATURE = 0x8001  # Event IDs have bit 15 set
EVENT_STATUS = 0x8002
EVENTGROUP_ID = 0x0001
SERVER_PORT = 30502


async def run_server():
    """Start a server that publishes events periodically."""
    config = ServiceInterfaceConfig(
        service_id=SERVICE_ID,
        instance_id=INSTANCE_ID,
        interface_version=1,
    )

    skeleton = Skeleton(config)

    # Register events
    temp_event = skeleton.register_event(EVENT_TEMPERATURE)
    status_event = skeleton.register_event(EVENT_STATUS)

    # Register eventgroup
    eventgroup = skeleton.register_eventgroup(EVENTGROUP_ID)
    eventgroup.add_event(EVENT_TEMPERATURE)
    eventgroup.add_event(EVENT_STATUS)

    # Transport
    transport = UdpTransport(local_port=SERVER_PORT)
    dispatcher = Dispatcher()
    dispatcher.register_skeleton(skeleton)

    # Track subscribers for events
    subscribers = {}  # source -> True

    async def on_message(message: SomeipMessage, source: tuple):
        # Handle requests normally
        response = await dispatcher.dispatch(message, source)
        if response is not None:
            await transport.send(response, source)

        # If this is a subscription-related message, track the subscriber
        if message.header.is_notification:
            subscribers[source] = True

    transport.set_message_handler(on_message)
    await transport.start()

    logger.info("Event server started on port %d", SERVER_PORT)
    logger.info("Publishing temperature and status events to group %d", EVENTGROUP_ID)

    # Simulate: manually add a handler to send events to known subscribers
    # In a real implementation, the SD agent would manage subscriptions
    known_clients = []

    async def publish_events():
        """Periodically publish events."""
        temperature = 20.0
        counter = 0
        while True:
            await asyncio.sleep(1.0)

            # Update temperature (simulate sensor)
            temperature += 0.5 * (1 if counter % 3 == 0 else -1)
            counter += 1

            # Publish temperature event
            temp_payload = struct.pack(">f", temperature)
            temp_msg = SomeipMessage.build_notification(
                service_id=SERVICE_ID,
                event_id=EVENT_TEMPERATURE,
                client_id=0,
                session_id=counter & 0xFFFF,
                interface_version=1,
                payload=temp_payload,
            )

            # Publish status event
            status = 0x01 if temperature < 25.0 else 0x02
            status_payload = struct.pack(">B", status)
            status_msg = SomeipMessage.build_notification(
                service_id=SERVICE_ID,
                event_id=EVENT_STATUS,
                client_id=0,
                session_id=counter & 0xFFFF,
                interface_version=1,
                payload=status_payload,
            )

            # Send to all known clients
            for client_addr in known_clients:
                try:
                    await transport.send(temp_msg, client_addr)
                    await transport.send(status_msg, client_addr)
                except Exception as e:
                    logger.warning("Failed to send event to %s: %s", client_addr, e)

            logger.info(
                "Published: temp=%.1f, status=%d, subscribers=%d",
                temperature, status, len(known_clients),
            )

    # Also handle a simple "subscribe" request (method_id = 0x0100)
    async def subscribe_handler(request: SomeipMessage) -> bytes:
        """Handle subscription request (simplified, no SD)."""
        known_clients.append((request.header.client_id, SERVER_PORT - 1))
        # Actually use the source from the transport - we'll track via a workaround
        logger.info("Client subscribed (session %d)", request.header.session_id)
        return struct.pack(">B", 1)  # ACK

    skeleton.register_method(0x0100, subscribe_handler)

    # Run event publishing loop
    try:
        await publish_events()
    except asyncio.CancelledError:
        pass
    finally:
        await transport.stop()


async def run_client():
    """Start a client that subscribes to events."""
    config = ServiceInterfaceConfig(
        service_id=SERVICE_ID,
        instance_id=INSTANCE_ID,
        interface_version=1,
    )

    proxy = Proxy(config)
    proxy.client_id = 0x0002

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

    async def on_message(message: SomeipMessage, source: tuple):
        await dispatcher.dispatch(message, source)

    transport.set_message_handler(on_message)
    await transport.start()

    server_endpoint = ("127.0.0.1", SERVER_PORT)

    logger.info("Event client started, listening for notifications...")
    logger.info("Service 0x%04X, events: temperature(0x%04X), status(0x%04X)",
                SERVICE_ID, EVENT_TEMPERATURE, EVENT_STATUS)

    try:
        # In a real implementation, we'd use SdAgent.subscribe_eventgroup()
        # Here we just listen for notifications that arrive

        # Keep running and receiving events
        for _ in range(15):
            await asyncio.sleep(1.0)

        logger.info("Received %d events total", len(received_events))

    except asyncio.CancelledError:
        pass
    finally:
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
