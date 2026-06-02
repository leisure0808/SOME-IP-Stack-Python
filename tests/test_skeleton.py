"""Tests for Skeleton."""

import asyncio

import pytest

from someip.config.service_config import ServiceInterfaceConfig
from someip.message.message import SomeipMessage
from someip.message.message_type import MessageType
from someip.message.return_code import ReturnCode
from someip.service.skeleton import Skeleton
from someip.service.field import Field


@pytest.mark.asyncio
class TestSkeleton:
    async def test_register_and_call_method(self):
        config = ServiceInterfaceConfig(
            service_id=0x1234, instance_id=0x0001, interface_version=0x01
        )
        skeleton = Skeleton(config)

        async def echo_handler(request: SomeipMessage) -> bytes:
            return request.payload

        skeleton.register_method(0x0001, echo_handler)

        request = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0001,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=b"\xDE\xAD",
        )

        response = await skeleton.handle_message(request)
        assert response is not None
        assert response.header.message_type == MessageType.RESPONSE
        assert response.header.return_code == ReturnCode.E_OK
        assert response.payload == b"\xDE\xAD"

    async def test_unknown_method_returns_error(self):
        config = ServiceInterfaceConfig(
            service_id=0x1234, instance_id=0x0001, interface_version=0x01
        )
        skeleton = Skeleton(config)

        request = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x9999,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=b"",
        )

        response = await skeleton.handle_message(request)
        assert response.header.message_type == MessageType.ERROR
        assert response.header.return_code == ReturnCode.E_UNKNOWN_METHOD

    async def test_fire_and_forget(self):
        config = ServiceInterfaceConfig(
            service_id=0x1234, instance_id=0x0001, interface_version=0x01
        )
        skeleton = Skeleton(config)

        called = False

        async def handler(request: SomeipMessage) -> bytes:
            nonlocal called
            called = True
            return b""

        skeleton.register_method(0x0001, handler)

        request = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0001,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=b"",
            fire_and_forget=True,
        )

        response = await skeleton.handle_message(request)
        assert response is None
        assert called

    async def test_field_getter(self):
        config = ServiceInterfaceConfig(
            service_id=0x1234, instance_id=0x0001, interface_version=0x01
        )
        skeleton = Skeleton(config)

        field = skeleton.register_field(0x0100)

        async def get_42():
            return b"\x42"

        field.set_getter_handler(get_42)

        request = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0100,  # getter_id = field_id
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=b"",
        )

        response = await skeleton.handle_message(request)
        assert response.header.return_code == ReturnCode.E_OK
        assert response.payload == b"\x42"

    async def test_handler_exception_returns_error(self):
        config = ServiceInterfaceConfig(
            service_id=0x1234, instance_id=0x0001, interface_version=0x01
        )
        skeleton = Skeleton(config)

        async def bad_handler(request: SomeipMessage) -> bytes:
            raise RuntimeError("boom")

        skeleton.register_method(0x0001, bad_handler)

        request = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0001,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=b"",
        )

        response = await skeleton.handle_message(request)
        assert response.header.return_code == ReturnCode.E_NOT_OK
