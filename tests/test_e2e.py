"""End-to-end test: simple_service example via localhost UDP."""

import asyncio
import struct

import pytest

from someip.config.service_config import ServiceInterfaceConfig
from someip.message.message import SomeipMessage
from someip.message.return_code import ReturnCode
from someip.service.skeleton import Skeleton
from someip.service.proxy import Proxy
from someip.service.dispatcher import Dispatcher
from someip.transport.udp import UdpTransport


@pytest.mark.asyncio
async def test_e2e_request_response():
    """End-to-end test: server echoes, client receives."""
    SERVICE_ID = 0x5000
    METHOD_ECHO = 0x0001
    METHOD_ADD = 0x0002

    # --- Server setup ---
    server_config = ServiceInterfaceConfig(
        service_id=SERVICE_ID, instance_id=0x0001, interface_version=1,
    )
    skeleton = Skeleton(server_config)

    async def echo_handler(request: SomeipMessage) -> bytes:
        return request.payload

    async def add_handler(request: SomeipMessage) -> bytes:
        a, b = struct.unpack(">II", request.payload[:8])
        return struct.pack(">I", a + b)

    skeleton.register_method(METHOD_ECHO, echo_handler)
    skeleton.register_method(METHOD_ADD, add_handler)

    server_transport = UdpTransport(local_port=0)
    server_dispatcher = Dispatcher()
    server_dispatcher.register_skeleton(skeleton)

    async def server_on_message(message: SomeipMessage, source: tuple):
        response = await server_dispatcher.dispatch(message, source)
        if response is not None:
            await server_transport.send(response, source)

    server_transport.set_message_handler(server_on_message)
    await server_transport.start()

    # --- Client setup ---
    client_config = ServiceInterfaceConfig(
        service_id=SERVICE_ID, instance_id=0x0001, interface_version=1,
    )
    proxy = Proxy(client_config)
    proxy.client_id = 0x0001

    client_transport = UdpTransport(local_port=0)
    client_dispatcher = Dispatcher()
    client_dispatcher.register_proxy(proxy)

    async def client_on_message(message: SomeipMessage, source: tuple):
        await client_dispatcher.dispatch(message, source)

    client_transport.set_message_handler(client_on_message)
    await client_transport.start()

    server_addr = ("127.0.0.1", server_transport.local_port)

    try:
        # --- Test echo ---
        request = proxy.build_request(METHOD_ECHO, b"Hello SOME/IP!")
        await client_transport.send(request, server_addr)
        response = await proxy.send_and_wait(request, timeout=2.0)
        assert response.header.return_code == ReturnCode.E_OK
        assert response.payload == b"Hello SOME/IP!"

        # --- Test add ---
        request = proxy.build_request(METHOD_ADD, struct.pack(">II", 42, 58))
        await client_transport.send(request, server_addr)
        response = await proxy.send_and_wait(request, timeout=2.0)
        assert response.header.return_code == ReturnCode.E_OK
        result = struct.unpack(">I", response.payload)[0]
        assert result == 100

        # --- Test second request (different session ID) ---
        request = proxy.build_request(METHOD_ADD, struct.pack(">II", 100, 200))
        await client_transport.send(request, server_addr)
        response = await proxy.send_and_wait(request, timeout=2.0)
        assert response.header.return_code == ReturnCode.E_OK
        result = struct.unpack(">I", response.payload)[0]
        assert result == 300

    finally:
        await client_transport.stop()
        await server_transport.stop()


@pytest.mark.asyncio
async def test_e2e_field_get_set():
    """End-to-end test: field getter/setter via localhost UDP."""
    SERVICE_ID = 0x5002
    FIELD_SPEED = 0x0100

    # --- Server ---
    server_config = ServiceInterfaceConfig(
        service_id=SERVICE_ID, instance_id=0x0001, interface_version=1,
    )
    skeleton = Skeleton(server_config)

    current_speed = 0.0

    field = skeleton.register_field(
        FIELD_SPEED,
        getter_id=FIELD_SPEED,
        setter_id=FIELD_SPEED + 1,
    )

    async def get_speed():
        return struct.pack(">f", current_speed)

    async def set_speed(value: bytes):
        nonlocal current_speed
        current_speed = struct.unpack(">f", value[:4])[0]
        return struct.pack(">f", current_speed)

    field.set_getter_handler(get_speed)
    field.set_setter_handler(set_speed)

    server_transport = UdpTransport(local_port=0)
    server_dispatcher = Dispatcher()
    server_dispatcher.register_skeleton(skeleton)

    async def server_on_message(message: SomeipMessage, source: tuple):
        response = await server_dispatcher.dispatch(message, source)
        if response is not None:
            await server_transport.send(response, source)

    server_transport.set_message_handler(server_on_message)
    await server_transport.start()

    # --- Client ---
    client_config = ServiceInterfaceConfig(
        service_id=SERVICE_ID, instance_id=0x0001, interface_version=1,
    )
    proxy = Proxy(client_config)
    proxy.client_id = 0x0002

    client_transport = UdpTransport(local_port=0)
    client_dispatcher = Dispatcher()
    client_dispatcher.register_proxy(proxy)

    async def client_on_message(message: SomeipMessage, source: tuple):
        await client_dispatcher.dispatch(message, source)

    client_transport.set_message_handler(client_on_message)
    await client_transport.start()

    server_addr = ("127.0.0.1", server_transport.local_port)

    try:
        # Get speed (should be 0.0)
        request = proxy.build_field_get(FIELD_SPEED)
        await client_transport.send(request, server_addr)
        response = await proxy.send_and_wait(request, timeout=2.0)
        assert response.header.return_code == ReturnCode.E_OK
        speed = struct.unpack(">f", response.payload)[0]
        assert speed == 0.0

        # Set speed to 80.5
        request = proxy.build_field_set(FIELD_SPEED, struct.pack(">f", 80.5))
        await client_transport.send(request, server_addr)
        response = await proxy.send_and_wait(request, timeout=2.0)
        assert response.header.return_code == ReturnCode.E_OK
        confirmed = struct.unpack(">f", response.payload)[0]
        assert confirmed == 80.5

        # Get speed again (should be 80.5)
        request = proxy.build_field_get(FIELD_SPEED)
        await client_transport.send(request, server_addr)
        response = await proxy.send_and_wait(request, timeout=2.0)
        speed = struct.unpack(">f", response.payload)[0]
        assert speed == 80.5

    finally:
        await client_transport.stop()
        await server_transport.stop()


@pytest.mark.asyncio
async def test_e2e_notification():
    """End-to-end test: event notification via localhost UDP."""
    SERVICE_ID = 0x5001
    EVENT_TEMP = 0x8001

    # --- Server ---
    server_transport = UdpTransport(local_port=0)
    received_by_client = []

    # Client side
    client_transport = UdpTransport(local_port=0)
    client_dispatcher = Dispatcher()

    def on_temp(message: SomeipMessage, source: tuple):
        received_by_client.append(message)

    client_dispatcher.register_notification_handler(SERVICE_ID, EVENT_TEMP, on_temp)

    async def client_on_message(message: SomeipMessage, source: tuple):
        await client_dispatcher.dispatch(message, source)

    client_transport.set_message_handler(client_on_message)
    await client_transport.start()
    await server_transport.start()

    try:
        # Server sends a notification
        notification = SomeipMessage.build_notification(
            service_id=SERVICE_ID,
            event_id=EVENT_TEMP,
            client_id=0,
            session_id=1,
            interface_version=1,
            payload=struct.pack(">f", 23.5),
        )
        client_addr = ("127.0.0.1", client_transport.local_port)
        await server_transport.send(notification, client_addr)

        await asyncio.sleep(0.1)

        assert len(received_by_client) == 1
        temp = struct.unpack(">f", received_by_client[0].payload)[0]
        assert abs(temp - 23.5) < 0.01

    finally:
        await client_transport.stop()
        await server_transport.stop()
