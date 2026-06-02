"""Tests for SOME/IP header serialization."""

import pytest

from someip.message.header import SomeipHeader, SOMEIP_HEADER_SIZE, SD_SERVICE_ID, SD_METHOD_ID
from someip.message.message_type import MessageType
from someip.message.return_code import ReturnCode


class TestSomeipHeader:
    def _make_header(self, **overrides):
        defaults = dict(
            service_id=0x1234,
            method_id=0x5678,
            length=8,  # minimum: just the remaining header
            client_id=0x0001,
            session_id=0x0001,
            protocol_version=0x01,
            interface_version=0x01,
            message_type=MessageType.REQUEST,
            return_code=ReturnCode.E_OK,
        )
        defaults.update(overrides)
        return SomeipHeader(**defaults)

    def test_serialize_size(self):
        header = self._make_header()
        data = header.serialize()
        assert len(data) == SOMEIP_HEADER_SIZE

    def test_roundtrip_request(self):
        header = self._make_header()
        data = header.serialize()
        parsed, consumed = SomeipHeader.deserialize(data)
        assert consumed == SOMEIP_HEADER_SIZE
        assert parsed.service_id == header.service_id
        assert parsed.method_id == header.method_id
        assert parsed.length == header.length
        assert parsed.client_id == header.client_id
        assert parsed.session_id == header.session_id
        assert parsed.protocol_version == header.protocol_version
        assert parsed.interface_version == header.interface_version
        assert parsed.message_type == header.message_type
        assert parsed.return_code == header.return_code

    def test_message_id(self):
        header = self._make_header(service_id=0xFFFF, method_id=0x8100)
        assert header.message_id == 0xFFFF8100

    def test_request_id(self):
        header = self._make_header(client_id=0xABCD, session_id=0x1234)
        assert header.request_id == 0xABCD1234

    def test_is_sd(self):
        header = self._make_header(service_id=SD_SERVICE_ID, method_id=SD_METHOD_ID)
        assert header.is_sd is True

    def test_is_not_sd(self):
        header = self._make_header(service_id=0x1234, method_id=0x0001)
        assert header.is_sd is False

    def test_is_notification(self):
        header = self._make_header(method_id=0x8001)
        assert header.is_notification is True

    def test_is_not_notification(self):
        header = self._make_header(method_id=0x0001)
        assert header.is_notification is False

    def test_response_header(self):
        header = self._make_header(
            message_type=MessageType.RESPONSE,
            return_code=ReturnCode.E_OK,
        )
        data = header.serialize()
        parsed, _ = SomeipHeader.deserialize(data)
        assert parsed.message_type == MessageType.RESPONSE
        assert parsed.return_code == ReturnCode.E_OK

    def test_error_header(self):
        header = self._make_header(
            message_type=MessageType.ERROR,
            return_code=ReturnCode.E_UNKNOWN_METHOD,
        )
        data = header.serialize()
        parsed, _ = SomeipHeader.deserialize(data)
        assert parsed.message_type == MessageType.ERROR
        assert parsed.return_code == ReturnCode.E_UNKNOWN_METHOD

    def test_notification_header(self):
        header = self._make_header(
            method_id=0x8001,
            message_type=MessageType.NOTIFICATION,
        )
        data = header.serialize()
        parsed, _ = SomeipHeader.deserialize(data)
        assert parsed.message_type == MessageType.NOTIFICATION
        assert parsed.is_notification is True

    def test_deserialize_too_short(self):
        from someip.error import MessageFormatError
        with pytest.raises(MessageFormatError, match="too short"):
            SomeipHeader.deserialize(b"\x00\x01\x02")

    def test_fire_and_forget(self):
        header = self._make_header(message_type=MessageType.REQUEST_NO_RETURN)
        assert header.message_type == MessageType.REQUEST_NO_RETURN
        assert header.message_type.is_fire_and_forget() is True

    def test_all_return_codes_roundtrip(self):
        for rc in ReturnCode:
            header = self._make_header(return_code=rc)
            data = header.serialize()
            parsed, _ = SomeipHeader.deserialize(data)
            assert parsed.return_code == rc

    def test_all_message_types_roundtrip(self):
        for mt in MessageType:
            header = self._make_header(message_type=mt)
            data = header.serialize()
            parsed, _ = SomeipHeader.deserialize(data)
            assert parsed.message_type == mt

    def test_length_field_with_payload(self):
        # Length = 8 (remaining header) + 100 (payload) = 108
        header = self._make_header(length=108)
        data = header.serialize()
        parsed, _ = SomeipHeader.deserialize(data)
        assert parsed.length == 108
