"""SOME/IP Service Discovery Example.

Demonstrates how services discover each other via the SD protocol:
- Server: offers a service via SD multicast
- Client: finds the service and receives the offer

Uses separate transports for SD and service messages:
- SD transport: handles OfferService, FindService on the SD port (30490)
- Service transport: handles actual service method calls

Run in two terminals:
  Terminal 1: python -m examples.sd_discovery server
  Terminal 2: python -m examples.sd_discovery client
"""

import asyncio
import logging
import sys

from someip.config.service_config import ServiceInterfaceConfig
from someip.config.stack_config import StackConfiguration
from someip.message.message import SomeipMessage
from someip.message.return_code import ReturnCode
from someip.sd.agent import SdAgent, ServiceOffer
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

SD_MULTICAST = "224.224.224.245"


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

    # Service transport for SOME/IP messages (method calls)
    transport = UdpTransport(local_port=SERVER_PORT)

    # SD transport on the SD port for SD messages
    sd_transport = UdpTransport(local_port=SD_PORT)

    # Dispatcher
    dispatcher = Dispatcher()
    dispatcher.register_skeleton(skeleton)

    # Stack configuration
    stack_config = StackConfiguration(
        unicast_address="127.0.0.1",
        sd_multicast_address=SD_MULTICAST,
        sd_port=SD_PORT,
    )

    # SdAgent with separate SD transport
    sd_agent = SdAgent(transport, stack_config, sd_transport=sd_transport)

    # Service message routing
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
        major_version=1,
        minor_version=0,
        ttl=0xFFFFFF,
        address="127.0.0.1",
        port=SERVER_PORT,
        protocol=17,
    )
    await sd_agent.offer_service(offer)

    logger.info("Server started on port %d, SD port %d", SERVER_PORT, SD_PORT)
    logger.info("Offering service 0x%04X on 127.0.0.1:%d", SERVICE_ID, SERVER_PORT)

    try:
        while True:
            await asyncio.sleep(3600.0)  # Run forever
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

    # Service transport for SOME/IP messages (method calls)
    transport = UdpTransport(local_port=0)

    # SD transport for SD messages
    sd_transport = UdpTransport(local_port=0)

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

    # Stack configuration
    stack_config = StackConfiguration(
        unicast_address="127.0.0.1",
        sd_multicast_address=SD_MULTICAST,
        sd_port=SD_PORT,
    )
    sd_agent = SdAgent(transport, stack_config, sd_transport=sd_transport)
    sd_agent.set_service_available_handler(on_service_available)

    # Service message routing
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

    logger.info("Client started, looking for service 0x%04X...", SERVICE_ID)

    # Send FindService via SdAgent
    await sd_agent.find_service(SERVICE_ID)

    try:
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
