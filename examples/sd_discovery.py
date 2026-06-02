"""SOME/IP Service Discovery Example.

Demonstrates how services discover each other via the SD protocol:
- Server: offers a service via SD multicast
- Client: finds the service and receives the offer

This example uses UDP multicast on 224.224.224.245:30490 (standard SD address).

Run in two terminals:
  Terminal 1: python -m examples.sd_discovery server
  Terminal 2: python -m examples.sd_discovery client

Note: On Windows, multicast may require admin privileges or specific
network configuration. If multicast doesn't work, this example falls
back to unicast on localhost.
"""

import asyncio
import logging
import struct
import sys

from someip.config.service_config import ServiceInterfaceConfig
from someip.config.stack_config import StackConfiguration
from someip.message.message import SomeipMessage
from someip.message.return_code import ReturnCode
from someip.sd.agent import SdAgent, ServiceOffer
from someip.sd.entry import SdEntry, SdEntryType
from someip.sd.message import SdMessage
from someip.sd.option import IPv4EndpointOption, SdOptionType
from someip.service.skeleton import Skeleton
from someip.service.proxy import Proxy
from someip.service.dispatcher import Dispatcher
from someip.transport.udp import UdpTransport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("sd_discovery")

# Service definition
SERVICE_ID = 0x6000
INSTANCE_ID = 0x0001
METHOD_PING = 0x0001
SERVER_PORT = 30504
SD_PORT = 30490


async def run_server():
    """Start a server that offers its service via SD."""
    config = ServiceInterfaceConfig(
        service_id=SERVICE_ID,
        instance_id=INSTANCE_ID,
        interface_version=1,
    )

    skeleton = Skeleton(config)

    async def ping_handler(request: SomeipMessage) -> bytes:
        logger.info("Ping received, sending pong")
        return b"PONG"

    skeleton.register_method(METHOD_PING, ping_handler)

    # Transport
    transport = UdpTransport(local_port=SERVER_PORT)

    # Dispatcher
    dispatcher = Dispatcher()
    dispatcher.register_skeleton(skeleton)

    # SD Agent
    stack_config = StackConfiguration(
        sd_multicast_address="224.224.224.245",
        sd_port=SD_PORT,
        unicast_address="127.0.0.1",
    )
    sd_agent = SdAgent(transport, stack_config)

    # Wire up message flow
    async def on_message(message: SomeipMessage, source: tuple):
        if message.header.is_sd:
            # Let SD agent handle SD messages
            sd_agent._on_message_received(message, source)
        else:
            response = await dispatcher.dispatch(message, source)
            if response is not None:
                await transport.send(response, source)

    transport.set_message_handler(on_message)
    await transport.start()

    # Also start a separate UDP listener on SD port for SD messages
    sd_transport = UdpTransport(local_port=SD_PORT)
    sd_transport.set_message_handler(on_message)
    await sd_transport.start()

    logger.info("Server started on port %d, SD port %d", SERVER_PORT, SD_PORT)

    # Manually broadcast an OfferService message
    offer = ServiceOffer(
        service_id=SERVICE_ID,
        instance_id=INSTANCE_ID,
        major_version=1,
        minor_version=0,
        address="127.0.0.1",
        port=SERVER_PORT,
        protocol=17,
    )

    # Build and send OfferService manually
    entry = SdEntry(
        entry_type=SdEntryType.OFFER_SERVICE,
        service_id=SERVICE_ID,
        instance_id=INSTANCE_ID,
        major_version=1,
        ttl=0xFFFFFF,
        minor_version=0,
    )
    option = IPv4EndpointOption(
        option_type=SdOptionType.IPv4_ENDPOINT,
        address="127.0.0.1",
        port=SERVER_PORT,
        protocol=17,
    )
    sd_msg = SdMessage(entries=[entry], options=[option])
    offer_data = sd_msg.serialize()
    offer_msg = SomeipMessage.deserialize(offer_data)

    # Send offer periodically
    logger.info("Offering service 0x%04X on 127.0.0.1:%d", SERVICE_ID, SERVER_PORT)

    try:
        while True:
            # Send offer to SD multicast
            try:
                await sd_transport.send(
                    offer_msg,
                    ("224.224.224.245", SD_PORT),
                )
            except Exception:
                # Multicast may fail on some systems, also send unicast
                pass

            # Also send as unicast for local testing
            await transport.send(offer_msg, ("127.0.0.1", SD_PORT + 1))

            logger.info("OfferService sent")
            await asyncio.sleep(2.0)

    except asyncio.CancelledError:
        pass
    finally:
        await sd_agent.stop()
        await sd_transport.stop()
        await transport.stop()
        logger.info("Server stopped")


async def run_client():
    """Start a client that finds services via SD."""
    config = ServiceInterfaceConfig(
        service_id=SERVICE_ID,
        instance_id=INSTANCE_ID,
        interface_version=1,
    )

    proxy = Proxy(config)
    proxy.client_id = 0x0004

    # We need a transport on SD_PORT + 1 for unicast SD
    client_sd_port = SD_PORT + 1
    transport = UdpTransport(local_port=client_sd_port)

    # Dispatcher
    dispatcher = Dispatcher()
    dispatcher.register_proxy(proxy)

    discovered_services = []

    def on_service_available(service_id, instance_id, offer):
        logger.info(
            "Service DISCOVERED: 0x%04X instance 0x%04X at %s:%d",
            service_id, instance_id, offer.address, offer.port,
        )
        discovered_services.append(offer)

    # SD Agent
    stack_config = StackConfiguration(
        sd_multicast_address="224.224.224.245",
        sd_port=SD_PORT,
        unicast_address="127.0.0.1",
    )
    sd_agent = SdAgent(transport, stack_config)
    sd_agent.set_service_available_handler(on_service_available)

    # Wire up message flow
    async def on_message(message: SomeipMessage, source: tuple):
        if message.header.is_sd:
            sd_agent._on_message_received(message, source)
        else:
            await dispatcher.dispatch(message, source)

    transport.set_message_handler(on_message)
    await transport.start()

    # Also listen on SD port for multicast
    sd_transport = UdpTransport(local_port=0)
    sd_transport.set_message_handler(on_message)
    await sd_transport.start()

    logger.info("Client started, looking for service 0x%04X...", SERVICE_ID)

    # Send FindService manually
    find_entry = SdEntry(
        entry_type=SdEntryType.FIND_SERVICE,
        service_id=SERVICE_ID,
        instance_id=0xFFFF,
        major_version=0xFF,
        ttl=0xFFFFFF,
    )
    find_msg = SdMessage(entries=[find_entry])
    find_data = find_msg.serialize()
    find_someip_msg = SomeipMessage.deserialize(find_data)

    try:
        # Send find request
        await sd_transport.send(find_someip_msg, ("127.0.0.1", SD_PORT))
        logger.info("FindService sent")

        # Wait for service discovery
        for i in range(10):
            await asyncio.sleep(1.0)
            if discovered_services:
                break

        if not discovered_services:
            logger.warning("No service discovered after 10 seconds")
            logger.info("Try starting the server first")
            return

        # Once discovered, call the ping method
        offer = discovered_services[0]
        server_endpoint = (offer.address, offer.port)
        logger.info("Calling ping method on discovered service...")

        request = proxy.build_request(METHOD_PING, b"PING")
        await transport.send(request, server_endpoint)
        response = await proxy.send_and_wait(request, timeout=3.0)

        if response.header.return_code == ReturnCode.E_OK:
            logger.info(
                "Ping response: %s",
                response.payload.decode("ascii", errors="replace"),
            )
        else:
            logger.error("Ping failed: %s", response.header.return_code.name)

        logger.info("SD discovery example completed!")

    except Exception as e:
        logger.error("Client error: %s", e)
    finally:
        await sd_agent.stop()
        await sd_transport.stop()
        await transport.stop()


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m examples.sd_discovery [server|client]")
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
