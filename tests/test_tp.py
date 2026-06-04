"""Tests for SOME/IP-TP segmentation and reassembly."""

import pytest

from someip.message.header import SOMEIP_HEADER_SIZE
from someip.message.message import SomeipMessage
from someip.message.message_type import MessageType
from someip.message.return_code import ReturnCode
from someip.message.tp import (
    TpSegmenter,
    TpReassembler,
    build_tp_extension,
    parse_tp_header,
    TP_HEADER_EXT_SIZE,
    TP_MORE_SEGMENTS_FLAG,
)


class TestTpExtension:
    def test_build_and_parse_no_more(self):
        ext = build_tp_extension(offset=0, more_segments=False)
        offset, more, consumed = parse_tp_header(ext)
        assert offset == 0
        assert more is False
        assert consumed == 4

    def test_build_and_parse_with_more(self):
        ext = build_tp_extension(offset=1024, more_segments=True)
        offset, more, consumed = parse_tp_header(ext)
        assert offset == 1024
        assert more is True

    def test_offset_zero_with_more_flag(self):
        ext = build_tp_extension(offset=0, more_segments=True)
        offset, more, _ = parse_tp_header(ext)
        assert offset == 0
        assert more is True

    def test_large_offset(self):
        ext = build_tp_extension(offset=0x0FFFFFFF, more_segments=False)
        offset, more, _ = parse_tp_header(ext)
        assert offset == 0x0FFFFFFF
        assert more is False


class TestTpSegmenter:
    def test_small_message_not_segmented(self):
        msg = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0001,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=b"\x01\x02\x03\x04",
        )
        segmenter = TpSegmenter(mtu=1392)
        segments = segmenter.segment(msg)
        assert len(segments) == 1
        # Should be the original message (no TP flag)
        assert not segments[0].header.is_tp

    def test_large_message_segmented(self):
        payload = bytes(range(256)) * 4  # 1024 bytes
        msg = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0001,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=payload,
        )
        segmenter = TpSegmenter(mtu=512)  # Force segmentation
        segments = segmenter.segment(msg)

        assert len(segments) > 1
        # All segments should have TP flag
        for seg in segments:
            assert seg.header.is_tp

        # First segment should have offset 0
        first_offset, first_more, _ = parse_tp_header(segments[0].payload, 0)
        assert first_offset == 0
        assert first_more is True

        # Last segment should have more_segments=False
        last_offset, last_more, _ = parse_tp_header(segments[-1].payload, 0)
        assert last_more is False

    def test_segments_preserve_header_fields(self):
        payload = bytes(range(256)) * 4
        msg = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0001,
            client_id=0x0001, session_id=0x0042,
            interface_version=0x01, payload=payload,
        )
        segmenter = TpSegmenter(mtu=512)
        segments = segmenter.segment(msg)

        for seg in segments:
            assert seg.header.service_id == 0x1234
            assert seg.header.method_id == 0x0001
            assert seg.header.client_id == 0x0001
            assert seg.header.session_id == 0x0042


class TestTpReassembler:
    def test_reassemble_two_segments(self):
        # Create a large message and segment it
        payload = bytes(range(256)) * 4  # 1024 bytes
        msg = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0001,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=payload,
        )
        segmenter = TpSegmenter(mtu=512)
        segments = segmenter.segment(msg)

        # Reassemble
        reassembler = TpReassembler(timeout=5.0)
        result = None
        for seg in segments:
            result = reassembler.add_segment(seg)

        # The reassembler returns a SomeipMessage
        assert isinstance(result, SomeipMessage)
        assert result.payload == payload
        assert result.header.service_id == 0x1234
        assert result.header.method_id == 0x0001
        assert result.header.message_type == MessageType.REQUEST

    def test_reassemble_in_order(self):
        payload = b"A" * 1000
        msg = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0001,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=payload,
        )
        segmenter = TpSegmenter(mtu=512)
        segments = segmenter.segment(msg)

        reassembler = TpReassembler()
        for i, seg in enumerate(segments):
            result = reassembler.add_segment(seg)
            if i == len(segments) - 1:
                assert isinstance(result, SomeipMessage)
                assert result.payload == payload
            else:
                assert result is None

    def test_reset_clears_state(self):
        payload = b"X" * 1000
        msg = SomeipMessage.build_request(
            service_id=0x1234, method_id=0x0001,
            client_id=0x0001, session_id=0x0001,
            interface_version=0x01, payload=payload,
        )
        segmenter = TpSegmenter(mtu=512)
        segments = segmenter.segment(msg)

        reassembler = TpReassembler()
        # Add only first segment
        reassembler.add_segment(segments[0])
        assert len(reassembler._pending) == 1

        # Reset all
        reassembler.reset()
        assert len(reassembler._pending) == 0
