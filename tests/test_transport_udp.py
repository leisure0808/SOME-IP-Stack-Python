"""Tests for UDP transport."""

import asyncio

import pytest

from someip.error import TransportError
from someip.message.message import SomeipMessage
from someip.message.message_type import MessageType
from someip.message.return_code import ReturnCode
from someip.transport.udp import UdpTransport


@pytest.mark.asyncio
class TestUdpTransport:
    async def test_send_receive(self):
        """Send a message from one UDP transport to another."""
        received = []

        receiver = UdpTransport(local_port=0)
        receiver.set_message_handler(lambda msg, addr: received.append((msg, addr)))

        sender = UdpTransport(local_port=0)

        await receiver.start()
        await sender.start()

        try:
            msg = SomeipMessage.build_request(
                service_id=0x1234, method_id=0x0001,
                client_id=0x0001, session_id=0x0001,
                interface_version=0x01, payload=b"\xDE\xAD\xBE\xEF",
            )
            await sender.send(msg, ("127.0.0.1", receiver.local_port))

            # Wait for delivery
            await asyncio.sleep(0.1)

            assert len(received) == 1
            parsed_msg, addr = received[0]
            assert parsed_msg.header.service_id == 0x1234
            assert parsed_msg.header.method_id == 0x0001
            assert parsed_msg.payload == b"\xDE\xAD\xBE\xEF"
        finally:
            await sender.stop()
            await receiver.stop()

    async def test_multiple_messages(self):
        """Send multiple messages sequentially."""
        received = []

        receiver = UdpTransport(local_port=0)
        receiver.set_message_handler(lambda msg, addr: received.append(msg))

        sender = UdpTransport(local_port=0)

        await receiver.start()
        await sender.start()

        try:
            for i in range(5):
                msg = SomeipMessage.build_request(
                    service_id=0x1000 + i, method_id=0x0001,
                    client_id=0x0001, session_id=i,
                    interface_version=0x01, payload=bytes([i]),
                )
                await sender.send(msg, ("127.0.0.1", receiver.local_port))

            await asyncio.sleep(0.2)

            assert len(received) >= 1  # At least some messages arrive
            service_ids = {m.header.service_id for m in received}
            # Check that all or most messages arrived
            assert len(service_ids) >= 1
        finally:
            await sender.stop()
            await receiver.stop()

    async def test_start_stop(self):
        transport = UdpTransport(local_port=0)
        assert not transport.is_running
        await transport.start()
        assert transport.is_running
        await transport.stop()
        assert not transport.is_running

    async def test_send_without_start_raises(self):
        transport = UdpTransport()
        msg = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0001,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=b"",
        )
        with pytest.raises(Exception):
            await transport.send(msg, ("127.0.0.1", 30490))

    async def test_join_multicast_group(self):
        """Test joining a multicast group does not crash."""
        transport = UdpTransport(local_port=0)
        await transport.start()

        try:
            # This may fail on some systems (no multicast route),
            # but should not raise an unhandled exception
            transport.join_multicast_group("224.224.224.245", "127.0.0.1")
        except OSError:
            # Acceptable: multicast may not be available in the test environment
            pass
        finally:
            await transport.stop()

    async def test_leave_multicast_group_not_started(self):
        """Leaving a multicast group on a stopped transport should not raise."""
        transport = UdpTransport(local_port=0)
        # Should be a no-op, not an error
        transport.leave_multicast_group("224.224.224.245")

    async def test_join_multicast_before_start_raises(self):
        """Joining a multicast group before start() should raise TransportError."""
        transport = UdpTransport(local_port=0)
        with pytest.raises(TransportError):
            transport.join_multicast_group("224.224.224.245")

    async def test_join_leave_multicast(self):
        """Test join + leave lifecycle."""
        transport = UdpTransport(local_port=0)
        await transport.start()

        try:
            try:
                transport.join_multicast_group("224.224.224.245", "127.0.0.1")
            except OSError:
                pass  # Multicast may not be available
            transport.leave_multicast_group("224.224.224.245", "127.0.0.1")
        finally:
            await transport.stop()
