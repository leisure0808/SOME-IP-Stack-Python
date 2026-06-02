"""Tests for Field (getter/setter/notifier)."""

import asyncio

import pytest

from someip.message.message import SomeipMessage
from someip.message.return_code import ReturnCode
from someip.service.field import Field


@pytest.mark.asyncio
class TestField:
    async def test_getter(self):
        field = Field(service_id=0x1234, field_id=0x0100)

        async def get_value():
            return b"\x42"

        field.set_getter_handler(get_value)

        request = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0100,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=b"",
        )

        response = await field.handle_get(request)
        assert response.header.return_code == ReturnCode.E_OK
        assert response.payload == b"\x42"

    async def test_setter(self):
        field = Field(service_id=0x1234, field_id=0x0100)

        stored = None

        async def set_value(value: bytes) -> bytes:
            nonlocal stored
            stored = value
            return value

        field.set_setter_handler(set_value)

        request = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0101,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=b"\xAB\xCD",
        )

        response = await field.handle_set(request)
        assert response.header.return_code == ReturnCode.E_OK
        assert response.payload == b"\xAB\xCD"
        assert stored == b"\xAB\xCD"

    async def test_getter_not_set_returns_error(self):
        field = Field(service_id=0x1234, field_id=0x0100)

        request = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0100,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=b"",
        )

        response = await field.handle_get(request)
        assert response.header.return_code == ReturnCode.E_UNKNOWN_METHOD

    async def test_setter_not_set_returns_error(self):
        field = Field(service_id=0x1234, field_id=0x0100)

        request = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0101,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=b"\x01",
        )

        response = await field.handle_set(request)
        assert response.header.return_code == ReturnCode.E_UNKNOWN_METHOD

    async def test_notifier_on_set(self):
        field = Field(service_id=0x1234, field_id=0x0100, notifier_id=0x0100)
        notified_values = []

        field.add_notifier_handler(lambda v: notified_values.append(v))

        async def set_value(value: bytes) -> bytes:
            return value

        field.set_setter_handler(set_value)

        request = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0101,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=b"\xFF",
        )

        await field.handle_set(request)
        assert len(notified_values) == 1
        assert notified_values[0] == b"\xFF"

    async def test_field_ids(self):
        field = Field(
            service_id=0x1234,
            field_id=0x0100,
            getter_id=0x0100,
            setter_id=0x0101,
            notifier_id=0x8100,
        )
        assert field.getter_id == 0x0100
        assert field.setter_id == 0x0101
        assert field.notifier_id == 0x8100
        assert field.has_getter is False
        assert field.has_setter is False
        assert field.has_notifier is True
