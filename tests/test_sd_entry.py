"""Tests for SD entry serialization."""

import pytest

from someip.error import MessageFormatError
from someip.sd.entry import SdEntry, SdEntryType, SD_ENTRY_SIZE


class TestSdEntry:
    def test_offer_service_serialize(self):
        entry = SdEntry(
            entry_type=SdEntryType.OFFER_SERVICE,
            service_id=0x1234,
            instance_id=0x0001,
            major_version=0x01,
            ttl=0xFFFFFF,
            minor_version=0x00000001,
        )
        data = entry.serialize()
        assert len(data) == SD_ENTRY_SIZE

    def test_offer_service_roundtrip(self):
        entry = SdEntry(
            entry_type=SdEntryType.OFFER_SERVICE,
            service_id=0x5000,
            instance_id=0x0002,
            major_version=0x03,
            ttl=0x000030,
            minor_version=0x00000042,
        )
        data = entry.serialize()
        parsed, consumed = SdEntry.deserialize(data)
        assert consumed == SD_ENTRY_SIZE
        assert parsed.entry_type == SdEntryType.OFFER_SERVICE
        assert parsed.service_id == 0x5000
        assert parsed.instance_id == 0x0002
        assert parsed.major_version == 0x03
        assert parsed.ttl == 0x000030
        assert parsed.minor_version == 0x00000042

    def test_find_service_roundtrip(self):
        entry = SdEntry(
            entry_type=SdEntryType.FIND_SERVICE,
            service_id=0x6000,
            instance_id=0xFFFF,
            major_version=0xFF,
            ttl=0xFFFFFF,
        )
        data = entry.serialize()
        parsed, _ = SdEntry.deserialize(data)
        assert parsed.entry_type == SdEntryType.FIND_SERVICE
        assert parsed.service_id == 0x6000
        assert parsed.instance_id == 0xFFFF

    def test_subscribe_eventgroup_roundtrip(self):
        entry = SdEntry(
            entry_type=SdEntryType.SUBSCRIBE_EVENTGROUP,
            service_id=0x1234,
            instance_id=0x0001,
            major_version=0x01,
            ttl=0xFFFFFF,
            eventgroup_id=0x0001,
        )
        data = entry.serialize()
        parsed, _ = SdEntry.deserialize(data)
        assert parsed.entry_type == SdEntryType.SUBSCRIBE_EVENTGROUP
        assert parsed.eventgroup_id == 0x0001

    def test_stop_offer_ttl_zero(self):
        entry = SdEntry(
            entry_type=SdEntryType.OFFER_SERVICE,
            service_id=0x1234,
            instance_id=0x0001,
            major_version=0x01,
            ttl=0,
            minor_version=0,
        )
        assert entry.is_stop is True

    def test_offer_not_stop(self):
        entry = SdEntry(
            entry_type=SdEntryType.OFFER_SERVICE,
            service_id=0x1234,
            instance_id=0x0001,
            major_version=0x01,
            ttl=3,
        )
        assert entry.is_stop is False

    def test_is_service_entry(self):
        assert SdEntry(entry_type=SdEntryType.FIND_SERVICE, service_id=1, instance_id=1, major_version=1, ttl=1).is_service_entry is True
        assert SdEntry(entry_type=SdEntryType.OFFER_SERVICE, service_id=1, instance_id=1, major_version=1, ttl=1).is_service_entry is True
        assert SdEntry(entry_type=SdEntryType.SUBSCRIBE_EVENTGROUP, service_id=1, instance_id=1, major_version=1, ttl=1).is_service_entry is False

    def test_is_eventgroup_entry(self):
        assert SdEntry(entry_type=SdEntryType.SUBSCRIBE_EVENTGROUP, service_id=1, instance_id=1, major_version=1, ttl=1).is_eventgroup_entry is True
        assert SdEntry(entry_type=SdEntryType.SUBSCRIBE_EVENTGROUP_ACK, service_id=1, instance_id=1, major_version=1, ttl=1).is_eventgroup_entry is True

    def test_deserialize_too_short(self):
        with pytest.raises(MessageFormatError, match="too short"):
            SdEntry.deserialize(b"\x00" * 8)
