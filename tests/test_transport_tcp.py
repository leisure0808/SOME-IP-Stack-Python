"""Tests for TCP transport."""

import asyncio

import pytest

from someip.message.message import SomeipMessage
from someip.transport.tcp import TcpTransport


@pytest.mark.asyncio
class TestTcpTransport:
    async def test_connect_and_send(self):
        """Server accepts connection and receives a message."""
        received = []

        server = TcpTransport()
        server.set_message_handler(lambda msg, addr: received.append((msg, addr)))
        await server.start(listen_port=0)

        client = TcpTransport()
        client.set_message_handler(lambda msg, addr: received.append((msg, addr)))

        try:
            # Client connects to server
            await client.connect("127.0.0.1", server.listen_port)
            await asyncio.sleep(0.05)

            # Client sends a message to server
            msg = SomeipMessage.build_request(
                service_id=0x5000, method_id=0x0100,
                client_id=0x0001, session_id=0x0001,
                interface_version=0x01, payload=b"\xCA\xFE",
            )

            # Find the server's address from client's perspective
            # The server endpoint we connected to
            await client.send(msg, ("127.0.0.1", server.listen_port))
            await asyncio.sleep(0.1)

            assert len(received) >= 1
            parsed_msg = received[0][0]
            assert parsed_msg.header.service_id == 0x5000
            assert parsed_msg.payload == b"\xCA\xFE"
        finally:
            await client.stop()
            await server.stop()

    async def test_start_stop(self):
        transport = TcpTransport()
        assert not transport.is_running
        await transport.start(listen_port=0)
        assert transport.is_running
        await transport.stop()
        assert not transport.is_running
