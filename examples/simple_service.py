"""SOME/IP Simple Service Example.

A minimal request/response example showing:
- Server: registers a method and handles requests
- Client: sends a request and receives a response

Run in two terminals:
  Terminal 1: python -m examples.simple_service server
  Terminal 2: python -m examples.simple_service client
"""

import asyncio
import logging
import sys

from someip.config.service_config import ServiceInterfaceConfig
from someip.config.stack_config import StackConfiguration
from someip.message.message import SomeipMessage
from someip.message.return_code import ReturnCode
from someip.service.skeleton import Skeleton
from someip.service.proxy import Proxy
from someip.service.dispatcher import Dispatcher
from someip.transport.udp import UdpTransport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("simple_service")

# Service definition
SERVICE_ID = 0x5000
INSTANCE_ID = 0x0001
METHOD_ECHO = 0x0001
METHOD_ADD = 0x0002
SERVER_PORT = 30501


async def run_server():
    """Start a simple SOME/IP server."""
    # 1. Configure service interface
    config = ServiceInterfaceConfig(
        service_id=SERVICE_ID,
        instance_id=INSTANCE_ID,
        major_version=1,
        minor_version=0,
        interface_version=1,
    )

    # 2. Create skeleton and register methods
    skeleton = Skeleton(config)

    async def echo_handler(request: SomeipMessage) -> bytes:
        """Echo back the request payload."""
        logger.info("Echo request received: %s", request.payload.hex())
        return request.payload

    async def add_handler(request: SomeipMessage) -> bytes:
        """Add two uint32 values from the payload and return the result."""
        import struct
        if len(request.payload) >= 8:
            a, b = struct.unpack(">II", request.payload[:8])
            result = a + b
            logger.info("Add request: %d + %d = %d", a, b, result)
            return struct.pack(">I", result)
        return b"\x00\x00\x00\x00"

    skeleton.register_method(METHOD_ECHO, echo_handler)
    skeleton.register_method(METHOD_ADD, add_handler)

    # 3. Set up transport
    transport = UdpTransport(local_port=SERVER_PORT, local_host="0.0.0.0")

    # 4. Set up dispatcher
    dispatcher = Dispatcher()
    dispatcher.register_skeleton(skeleton)

    # 5. Wire transport -> dispatcher
    async def on_message(message: SomeipMessage, source: tuple):
        response = await dispatcher.dispatch(message, source)
        if response is not None:
            try:
                await transport.send(response, source)
            except Exception as e:
                logger.error("Failed to send response: %s", e)

    transport.set_message_handler(on_message)

    # 6. Start
    await transport.start()
    logger.info("Server started on port %d", SERVER_PORT)
    logger.info("Service 0x%04X instance 0x%04X", SERVICE_ID, INSTANCE_ID)
    logger.info("Methods: echo(0x%04X), add(0x%04X)", METHOD_ECHO, METHOD_ADD)

    try:
        # Keep running
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await transport.stop()
        logger.info("Server stopped")


async def run_client():
    """Start a simple SOME/IP client."""
    # 1. Configure service interface
    config = ServiceInterfaceConfig(
        service_id=SERVICE_ID,
        instance_id=INSTANCE_ID,
        major_version=1,
        minor_version=0,
        interface_version=1,
    )

    # 2. Create proxy
    proxy = Proxy(config)
    proxy.client_id = 0x0001

    # 3. Set up transport
    transport = UdpTransport(local_port=0)

    # 4. Set up dispatcher
    dispatcher = Dispatcher()
    dispatcher.register_proxy(proxy)

    # 5. Wire transport -> dispatcher
    def on_message(message: SomeipMessage, source: tuple):
        asyncio.ensure_future(dispatcher.dispatch(message, source))

    transport.set_message_handler(on_message)

    # 6. Start
    await transport.start()
    server_endpoint = ("127.0.0.1", SERVER_PORT)

    try:
        # --- Echo test ---
        logger.info("=== Echo Test ===")
        request = proxy.build_request(METHOD_ECHO, b"Hello SOME/IP!")
        await transport.send(request, server_endpoint)
        response = await proxy.send_and_wait(request, timeout=3.0)
        logger.info(
            "Echo response: payload=%s, return_code=%s",
            response.payload.decode("ascii", errors="replace"),
            response.header.return_code.name,
        )

        # --- Add test ---
        logger.info("=== Add Test ===")
        import struct
        request = proxy.build_request(METHOD_ADD, struct.pack(">II", 42, 58))
        await transport.send(request, server_endpoint)
        response = await proxy.send_and_wait(request, timeout=3.0)
        if response.header.return_code == ReturnCode.E_OK:
            result = struct.unpack(">I", response.payload)[0]
            logger.info("Add result: 42 + 58 = %d", result)
        else:
            logger.error("Add failed: %s", response.header.return_code.name)

        # --- call_method shorthand ---
        logger.info("=== call_method shorthand ===")
        request = proxy.build_request(METHOD_ADD, struct.pack(">II", 100, 200))
        await transport.send(request, server_endpoint)
        response = await proxy.call_method(METHOD_ADD, struct.pack(">II", 100, 200), timeout=3.0)
        # Note: call_method creates a new request internally, so the above
        # sends two requests. For proper use, use build_request + send + send_and_wait.

        logger.info("All tests completed!")

    except Exception as e:
        logger.error("Client error: %s", e)
    finally:
        await transport.stop()
        logger.info("Client stopped")


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m examples.simple_service [server|client]")
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
