"""Tests for SOME/IP complete message serialization."""

import struct

import pytest

from someip.error import MessageFormatError
from someip.message.header import SOMEIP_HEADER_SIZE
from someip.message.message import SomeipMessage
from someip.message.message_type import MessageType
from someip.message.return_code import ReturnCode


class TestSomeipMessage:
    def test_serialize_deserialize_request(self):
        payload = b"\x01\x02\x03\x04"
        msg = SomeipMessage.build_request(
            service_id=0x1234,
            method_id=0x0001,
            client_id=0x0001,
            session_id=0x0001,
            interface_version=0x01,
            payload=payload,
        )
        data = msg.serialize()
        parsed = SomeipMessage.deserialize(data)

        assert parsed.header.service_id == 0x1234
        assert parsed.header.method_id == 0x0001
        assert parsed.header.client_id == 0x0001
        assert parsed.header.session_id == 0x0001
        assert parsed.header.protocol_version == 0x01
        assert parsed.header.interface_version == 0x01
        assert parsed.header.message_type == MessageType.REQUEST
        assert parsed.header.return_code == ReturnCode.E_OK
        assert parsed.payload == payload

    def test_roundtrip_with_payload(self):
        payload = b"Hello SOME/IP"
        msg = SomeipMessage.build_request(
            service_id=0x1111,
            method_id=0x2222,
            client_id=0x3333,
            session_id=0x4444,
            interface_version=0x02,
            payload=payload,
        )
        data = msg.serialize()
        parsed = SomeipMessage.deserialize(data)
        assert parsed.payload == payload
        assert parsed.header.service_id == 0x1111

    def test_build_response(self):
        request = SomeipMessage.build_request(
            service_id=0x1234,
            method_id=0x0001,
            client_id=0x0001,
            session_id=0x0001,
            interface_version=0x01,
            payload=b"\x00",
        )
        response = SomeipMessage.build_response(
            request=request,
            interface_version=0x01,
            payload=b"\xAA\xBB",
        )
        assert response.header.service_id == request.header.service_id
        assert response.header.method_id == request.header.method_id
        assert response.header.client_id == request.header.client_id
        assert response.header.session_id == request.header.session_id
        assert response.header.message_type == MessageType.RESPONSE
        assert response.payload == b"\xAA\xBB"

    def test_build_error(self):
        request = SomeipMessage.build_request(
            service_id=0x1234,
            method_id=0x0001,
            client_id=0x0001,
            session_id=0x0001,
            interface_version=0x01,
            payload=b"",
        )
        error = SomeipMessage.build_error(
            request=request,
            interface_version=0x01,
            return_code=ReturnCode.E_UNKNOWN_METHOD,
        )
        assert error.header.message_type == MessageType.ERROR
        assert error.header.return_code == ReturnCode.E_UNKNOWN_METHOD
        assert error.payload == b""

    def test_build_notification(self):
        msg = SomeipMessage.build_notification(
            service_id=0x1234,
            event_id=0x0001,
            client_id=0x0000,
            session_id=0x0001,
            interface_version=0x01,
            payload=b"\xDE\xAD",
        )
        assert msg.header.message_type == MessageType.NOTIFICATION
        assert msg.header.method_id == 0x8001  # event_id with bit 15 set
        assert msg.header.is_notification is True

    def test_fire_and_forget(self):
        msg = SomeipMessage.build_request(
            service_id=0x1234,
            method_id=0x0001,
            client_id=0x0001,
            session_id=0x0001,
            interface_version=0x01,
            payload=b"",
            fire_and_forget=True,
        )
        assert msg.header.message_type == MessageType.REQUEST_NO_RETURN

    def test_length_field(self):
        payload = b"\x01\x02\x03\x04"
        msg = SomeipMessage.build_request(
            service_id=0x1234,
            method_id=0x0001,
            client_id=0x0001,
            session_id=0x0001,
            interface_version=0x01,
            payload=payload,
        )
        # Length = 8 (remaining header) + 4 (payload) = 12
        assert msg.header.length == 12

    def test_total_length(self):
        payload = b"\x01\x02\x03\x04"
        msg = SomeipMessage.build_request(
            service_id=0x1234,
            method_id=0x0001,
            client_id=0x0001,
            session_id=0x0001,
            interface_version=0x01,
            payload=payload,
        )
        assert msg.total_length == SOMEIP_HEADER_SIZE + len(payload)

    def test_empty_payload(self):
        msg = SomeipMessage.build_request(
            service_id=0x1234,
            method_id=0x0001,
            client_id=0x0001,
            session_id=0x0001,
            interface_version=0x01,
            payload=b"",
        )
        data = msg.serialize()
        parsed = SomeipMessage.deserialize(data)
        assert parsed.payload == b""
        assert parsed.header.length == 8  # just the remaining header

    def test_deserialize_too_short(self):
        with pytest.raises(MessageFormatError, match="too short"):
            SomeipMessage.deserialize(b"\x00\x01")

    def test_deserialize_incomplete(self):
        # Build a message, then truncate the serialized data
        msg = SomeipMessage.build_request(
            service_id=0x1234,
            method_id=0x0001,
            client_id=0x0001,
            session_id=0x0001,
            interface_version=0x01,
            payload=b"\x01\x02\x03\x04",
        )
        data = msg.serialize()
        with pytest.raises(MessageFormatError, match="Incomplete"):
            SomeipMessage.deserialize(data[:18])  # Truncate (need 20)

    def test_large_payload(self):
        payload = bytes(range(256)) * 10  # 2560 bytes
        msg = SomeipMessage.build_request(
            service_id=0x1234,
            method_id=0x0001,
            client_id=0x0001,
            session_id=0x0001,
            interface_version=0x01,
            payload=payload,
        )
        data = msg.serialize()
        parsed = SomeipMessage.deserialize(data)
        assert parsed.payload == payload

    def test_response_roundtrip_from_serialized_request(self):
        """Simulate full request-response cycle via serialization."""
        # Client sends request
        request = SomeipMessage.build_request(
            service_id=0x5000,
            method_id=0x0100,
            client_id=0x0001,
            session_id=0x0007,
            interface_version=0x01,
            payload=b"\x00\x01\x02\x03",
        )
        req_data = request.serialize()

        # Server receives and parses
        parsed_req = SomeipMessage.deserialize(req_data)

        # Server sends response
        response = SomeipMessage.build_response(
            request=parsed_req,
            interface_version=0x01,
            payload=b"\xFF\xFE\xFD",
            return_code=ReturnCode.E_OK,
        )
        resp_data = response.serialize()

        # Client receives and parses
        parsed_resp = SomeipMessage.deserialize(resp_data)

        assert parsed_resp.header.service_id == 0x5000
        assert parsed_resp.header.method_id == 0x0100
        assert parsed_resp.header.client_id == 0x0001
        assert parsed_resp.header.session_id == 0x0007
        assert parsed_resp.header.message_type == MessageType.RESPONSE
        assert parsed_resp.payload == b"\xFF\xFE\xFD"
