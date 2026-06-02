"""SOME/IP-TP (Transport Protocol) segmentation and reassembly.

SOME/IP-TP splits large messages that exceed the transport MTU into
segments, each with its own SOME/IP header with the TP flag set.

TP header extension (4 additional bytes after standard header):
    Offset  Size  Field
    0       4     Offset (bits 0-27) + More Segments flag (bit 31, MSB)
"""

import struct
import time
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..error import TpReassemblyError, MessageFormatError
from ..message.header import SOMEIP_HEADER_SIZE, SomeipHeader
from ..message.message import SomeipMessage
from ..message.message_type import MessageType

logger = logging.getLogger(__name__)

# TP header extension size (4 bytes)
TP_HEADER_EXT_SIZE = 4

# Bit mask for the "More Segments" flag (MSB of uint32)
TP_MORE_SEGMENTS_FLAG = 0x80000000

# Bit mask for the offset field (lower 28 bits)
TP_OFFSET_MASK = 0x0FFFFFFF


@dataclass
class TpSegment:
    """A single SOME/IP-TP segment."""

    header: SomeipHeader
    offset: int
    more_segments: bool
    payload: bytes


def parse_tp_header(data: bytes, offset: int = 0) -> Tuple[int, bool, int]:
    """Parse the 4-byte TP extension from a SOME/IP-TP message.

    Returns (tp_offset, more_segments, bytes_consumed).
    """
    if len(data) < offset + TP_HEADER_EXT_SIZE:
        raise MessageFormatError("TP header extension too short")

    raw = struct.unpack_from(">I", data, offset)[0]
    more_segments = bool(raw & TP_MORE_SEGMENTS_FLAG)
    tp_offset = raw & TP_OFFSET_MASK
    return tp_offset, more_segments, TP_HEADER_EXT_SIZE


def build_tp_extension(offset: int, more_segments: bool) -> bytes:
    """Build the 4-byte TP extension."""
    raw = (offset & TP_OFFSET_MASK)
    if more_segments:
        raw |= TP_MORE_SEGMENTS_FLAG
    return struct.pack(">I", raw)


class TpSegmenter:
    """Segments a large SOME/IP message into TP segments.

    The original message's header is preserved for each segment,
    with the TP flag set in the message type.
    """

    def __init__(self, mtu: int = 1392):
        """
        Args:
            mtu: Maximum payload size per segment (excluding headers).
        """
        self.mtu = mtu

    def segment(self, message: SomeipMessage) -> List[SomeipMessage]:
        """Segment a large message into TP segments.

        Returns a list of SOME/IP-TP messages. Each segment carries:
        - Standard SOME/IP header (16 bytes) with TP flag
        - TP extension (4 bytes): offset + more_segments
        - Segment payload
        """
        payload = message.payload

        if len(payload) <= self.mtu - TP_HEADER_EXT_SIZE:
            # No segmentation needed
            return [message]

        # Maximum payload per segment (minus TP extension)
        segment_payload_size = self.mtu - TP_HEADER_EXT_SIZE
        segments: List[SomeipMessage] = []
        offset = 0

        while offset < len(payload):
            chunk = payload[offset:offset + segment_payload_size]
            is_last = (offset + segment_payload_size) >= len(payload)

            # Build TP extension
            tp_ext = build_tp_extension(offset, more_segments=not is_last)

            # Build segment header (with TP flag)
            segment_msg_type = message.header.message_type.with_tp()
            segment_length = 8 + TP_HEADER_EXT_SIZE + len(chunk) + len(tp_ext)

            segment_header = SomeipHeader(
                service_id=message.header.service_id,
                method_id=message.header.method_id,
                length=8 + TP_HEADER_EXT_SIZE + len(chunk),
                client_id=message.header.client_id,
                session_id=message.header.session_id,
                protocol_version=message.header.protocol_version,
                interface_version=message.header.interface_version,
                message_type=segment_msg_type,
                return_code=message.header.return_code,
            )

            segment = SomeipMessage(
                header=segment_header,
                payload=tp_ext + chunk,
            )
            segments.append(segment)
            offset += segment_payload_size

        return segments


class TpReassembler:
    """Reassembles SOME/IP-TP segments into complete messages.

    Tracks segments by (service_id, method_id, client_id, session_id)
    and reassembles when all segments are received.
    """

    def __init__(self, timeout: float = 5.0):
        """
        Args:
            timeout: Maximum time to wait for all segments (seconds).
        """
        self._timeout = timeout
        # Key: (service_id, method_id, client_id, session_id)
        # Value: dict with 'segments', 'total_size', 'start_time'
        self._pending: Dict[tuple, dict] = {}

    def add_segment(self, message: SomeipMessage) -> Optional[SomeipMessage]:
        """Add a TP segment. Returns the complete message if all segments received.

        Returns None if more segments are needed.
        Raises TpReassemblyError on timeout or duplicate.
        """
        key = (
            message.header.service_id,
            message.header.method_id,
            message.header.client_id,
            message.header.session_id,
        )

        # Parse TP extension
        tp_offset, more_segments, _ = parse_tp_header(message.payload, 0)
        segment_payload = message.payload[TP_HEADER_EXT_SIZE:]

        now = time.monotonic()

        if key not in self._pending:
            # First segment for this message
            self._pending[key] = {
                "segments": [],
                "start_time": now,
            }

        entry = self._pending[key]

        # Check timeout
        if now - entry["start_time"] > self._timeout:
            del self._pending[key]
            raise TpReassemblyError(
                f"TP reassembly timeout for message {key}"
            )

        entry["segments"].append((tp_offset, segment_payload))

        if not more_segments:
            # All segments received, reassemble
            return self._reassemble(key, entry)

        return None

    def _reassemble(self, key: tuple, entry: dict) -> SomeipMessage:
        """Reassemble segments into a complete message."""
        segments = sorted(entry["segments"], key=lambda s: s[0])
        del self._pending[key]

        # Validate offsets are contiguous
        expected_offset = 0
        payload_parts = []
        for offset, data in segments:
            if offset != expected_offset:
                raise TpReassemblyError(
                    f"TP gap or overlap at offset {offset}, expected {expected_offset}"
                )
            payload_parts.append(data)
            expected_offset += len(data)

        full_payload = b"".join(payload_parts)

        # Build the reassembled message with non-TP header
        last_segment = segments[-1]
        # Use the header from the message context (service_id, method_id, etc.)
        # We need to reconstruct with non-TP message type
        # For now, construct from the key and last known header info
        # The caller should have the original header info
        return full_payload

    def reset(self, key: Optional[tuple] = None) -> None:
        """Reset reassembly state.

        If key is provided, only reset that specific message.
        Otherwise, reset all pending reassemblies.
        """
        if key:
            self._pending.pop(key, None)
        else:
            self._pending.clear()
