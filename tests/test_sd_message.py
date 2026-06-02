"""Tests for SD message serialization."""

import pytest

from someip.error import MessageFormatError
from someip.sd.entry import SdEntry, SdEntryType
from someip.sd.message import SdMessage
from someip.sd.option import IPv4EndpointOption, SdOptionType


class TestSdMessage:
    def test_offer_service_roundtrip(self):
        entry = SdEntry(
            entry_type=SdEntryType.OFFER_SERVICE,
            service_id=0x1234,
            instance_id=0x0001,
            major_version=0x01,
            ttl=0xFFFFFF,
            minor_version=0x00000001,
        )
        option = IPv4EndpointOption(
            option_type=SdOptionType.IPv4_ENDPOINT,
            address="192.168.1.100",
            port=30501,
            protocol=17,
        )
        sd_msg = SdMessage(entries=[entry], options=[option])

        data = sd_msg.serialize()
        parsed = SdMessage.deserialize(data)

        assert len(parsed.entries) == 1
        assert parsed.entries[0].entry_type == SdEntryType.OFFER_SERVICE
        assert parsed.entries[0].service_id == 0x1234
        assert len(parsed.options) == 1
        assert isinstance(parsed.options[0], IPv4EndpointOption)
        assert parsed.options[0].address == "192.168.1.100"

    def test_find_service_no_options(self):
        entry = SdEntry(
            entry_type=SdEntryType.FIND_SERVICE,
            service_id=0x5000,
            instance_id=0xFFFF,
            major_version=0xFF,
            ttl=0xFFFFFF,
        )
        sd_msg = SdMessage(entries=[entry])
        data = sd_msg.serialize()
        parsed = SdMessage.deserialize(data)

        assert len(parsed.entries) == 1
        assert parsed.entries[0].entry_type == SdEntryType.FIND_SERVICE
        assert len(parsed.options) == 0

    def test_multiple_entries(self):
        entries = [
            SdEntry(
                entry_type=SdEntryType.OFFER_SERVICE,
                service_id=0x1000 + i,
                instance_id=0x0001,
                major_version=0x01,
                ttl=0xFFFFFF,
                minor_version=0,
            )
            for i in range(3)
        ]
        sd_msg = SdMessage(entries=entries)
        data = sd_msg.serialize()
        parsed = SdMessage.deserialize(data)

        assert len(parsed.entries) == 3
        for i, entry in enumerate(parsed.entries):
            assert entry.service_id == 0x1000 + i

    def test_subscribe_eventgroup_roundtrip(self):
        entry = SdEntry(
            entry_type=SdEntryType.SUBSCRIBE_EVENTGROUP,
            service_id=0x1234,
            instance_id=0x0001,
            major_version=0x01,
            ttl=0xFFFFFF,
            eventgroup_id=0x0001,
        )
        sd_msg = SdMessage(entries=[entry])
        data = sd_msg.serialize()
        parsed = SdMessage.deserialize(data)

        assert parsed.entries[0].eventgroup_id == 0x0001

    def test_empty_sd_message(self):
        sd_msg = SdMessage()
        data = sd_msg.serialize()
        parsed = SdMessage.deserialize(data)
        assert len(parsed.entries) == 0
        assert len(parsed.options) == 0
