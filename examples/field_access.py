"""SOME/IP Field Access Example.

Demonstrates field getter, setter, and notifier:
- Server: provides a field with getter/setter/notifier
- Client: reads and writes the field, receives notifications

Run in two terminals:
  Terminal 1: python -m examples.field_access server
  Terminal 2: python -m examples.field_access client
"""

import asyncio
import logging
import struct
import sys

from someip.config.service_config import ServiceInterfaceConfig
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
logger = logging.getLogger("field_access")

# Service definition
SERVICE_ID = 0x5002
INSTANCE_ID = 0x0001
FIELD_SPEED = 0x0100
# Derived IDs: getter=0x0100, setter=0x0101, notifier=0x8100
SERVER_PORT = 30503


async def run_server():
    """Start a server with a speed field (getter/setter/notifier)."""
    config = ServiceInterfaceConfig(
        service_id=SERVICE_ID,
        instance_id=INSTANCE_ID,
        interface_version=1,
    )

    skeleton = Skeleton(config)

    # Current speed value
    current_speed = 0.0

    # Register field with getter, setter, and notifier
    field = skeleton.register_field(
        FIELD_SPEED,
        getter_id=FIELD_SPEED,
        setter_id=FIELD_SPEED + 1,
        notifier_id=0x8100,
    )

    async def get_speed() -> bytes:
        return struct.pack(">f", current_speed)

    async def set_speed(value: bytes) -> bytes:
        nonlocal current_speed
        new_speed = struct.unpack(">f", value[:4])[0]
        if new_speed < 0:
            new_speed = 0.0
        if new_speed > 300.0:
            new_speed = 300.0
        current_speed = new_speed
        logger.info("Speed set to %.1f km/h", current_speed)
        return struct.pack(">f", current_speed)

    field.set_getter_handler(get_speed)
    field.set_setter_handler(set_speed)

    # Add notifier handler
    field.add_notifier_handler(
        lambda value: logger.info("Speed notification sent: %s", value.hex())
    )

    # Transport + dispatcher
    transport = UdpTransport(local_port=SERVER_PORT)
    dispatcher = Dispatcher()
    dispatcher.register_skeleton(skeleton)

    async def on_message(message: SomeipMessage, source: tuple):
        response = await dispatcher.dispatch(message, source)
        if response is not None:
            await transport.send(response, source)

    transport.set_message_handler(on_message)
    await transport.start()

    logger.info("Field server started on port %d", SERVER_PORT)
    logger.info("Field 'speed': getter=0x%04X, setter=0x%04X, notifier=0x%04X",
                field.getter_id, field.setter_id, field.notifier_id)

    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await transport.stop()


async def run_client():
    """Start a client that reads and writes the speed field."""
    config = ServiceInterfaceConfig(
        service_id=SERVICE_ID,
        instance_id=INSTANCE_ID,
        interface_version=1,
    )

    proxy = Proxy(config)
    proxy.client_id = 0x0003

    transport = UdpTransport(local_port=0)
    dispatcher = Dispatcher()
    dispatcher.register_proxy(proxy)

    # Register notification handler for field notifier
    def on_speed_notification(message: SomeipMessage, source: tuple):
        speed = struct.unpack(">f", message.payload)[0]
        logger.info("Speed notification received: %.1f km/h", speed)

    dispatcher.register_notification_handler(SERVICE_ID, 0x8100, on_speed_notification)

    async def on_message(message: SomeipMessage, source: tuple):
        await dispatcher.dispatch(message, source)

    transport.set_message_handler(on_message)
    await transport.start()

    server_endpoint = ("127.0.0.1", SERVER_PORT)

    try:
        # --- Get speed (field getter) ---
        logger.info("=== Get Speed ===")
        request = proxy.build_field_get(FIELD_SPEED)
        await transport.send(request, server_endpoint)
        response = await proxy.send_and_wait(request, timeout=3.0)
        if response.header.return_code == ReturnCode.E_OK:
            speed = struct.unpack(">f", response.payload)[0]
            logger.info("Current speed: %.1f km/h", speed)

        # --- Set speed (field setter) ---
        logger.info("=== Set Speed ===")
        new_speed = 80.5
        request = proxy.build_field_set(FIELD_SPEED, struct.pack(">f", new_speed))
        await transport.send(request, server_endpoint)
        response = await proxy.send_and_wait(request, timeout=3.0)
        if response.header.return_code == ReturnCode.E_OK:
            confirmed_speed = struct.unpack(">f", response.payload)[0]
            logger.info("Speed set to: %.1f km/h", confirmed_speed)

        # --- Set another speed ---
        logger.info("=== Set Speed Again ===")
        request = proxy.build_field_set(FIELD_SPEED, struct.pack(">f", 120.0))
        await transport.send(request, server_endpoint)
        response = await proxy.send_and_wait(request, timeout=3.0)
        if response.header.return_code == ReturnCode.E_OK:
            confirmed_speed = struct.unpack(">f", response.payload)[0]
            logger.info("Speed confirmed: %.1f km/h", confirmed_speed)

        # --- Get speed again to verify ---
        logger.info("=== Verify Speed ===")
        request = proxy.build_field_get(FIELD_SPEED)
        await transport.send(request, server_endpoint)
        response = await proxy.send_and_wait(request, timeout=3.0)
        if response.header.return_code == ReturnCode.E_OK:
            speed = struct.unpack(">f", response.payload)[0]
            logger.info("Verified speed: %.1f km/h", speed)

        # --- Try invalid speed (above max) ---
        logger.info("=== Set Speed (clamped to max) ===")
        request = proxy.build_field_set(FIELD_SPEED, struct.pack(">f", 500.0))
        await transport.send(request, server_endpoint)
        response = await proxy.send_and_wait(request, timeout=3.0)
        if response.header.return_code == ReturnCode.E_OK:
            confirmed_speed = struct.unpack(">f", response.payload)[0]
            logger.info("Clamped speed: %.1f km/h (max 300)", confirmed_speed)

        logger.info("Field access tests completed!")

    except Exception as e:
        logger.error("Client error: %s", e)
    finally:
        await transport.stop()


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m examples.field_access [server|client]")
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
