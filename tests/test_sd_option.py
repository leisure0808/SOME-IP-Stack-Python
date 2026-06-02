"""Tests for SD option serialization."""

import pytest

from someip.error import MessageFormatError
from someip.sd.option import (
    ConfigOption,
    IPv4EndpointOption,
    SdOption,
    SdOptionType,
)


class TestIPv4EndpointOption:
    def test_serialize_deserialize(self):
        option = IPv4EndpointOption(
            option_type=SdOptionType.IPv4_ENDPOINT,
            address="192.168.1.100",
            port=30501,
            protocol=17,
        )
        data = option.serialize()

        parsed, consumed = SdOption.deserialize(data)
        assert isinstance(parsed, IPv4EndpointOption)
        assert parsed.address == "192.168.1.100"
        assert parsed.port == 30501
        assert parsed.protocol == 17

    def test_localhost(self):
        option = IPv4EndpointOption(
            option_type=SdOptionType.IPv4_ENDPOINT,
            address="127.0.0.1",
            port=30490,
            protocol=6,
        )
        data = option.serialize()
        parsed, _ = SdOption.deserialize(data)
        assert parsed.address == "127.0.0.1"
        assert parsed.port == 30490
        assert parsed.protocol == 6

    def test_sd_endpoint_type(self):
        option = IPv4EndpointOption(
            option_type=SdOptionType.IPv4_SD_ENDPOINT,
            address="224.224.224.245",
            port=30490,
            protocol=17,
        )
        data = option.serialize()
        parsed, _ = SdOption.deserialize(data)
        assert parsed.option_type == SdOptionType.IPv4_SD_ENDPOINT
        assert parsed.address == "224.224.224.245"


class TestConfigOption:
    def test_serialize_deserialize(self):
        option = ConfigOption(configuration={"key1": "value1", "key2": "value2"})
        data = option.serialize()

        parsed, consumed = SdOption.deserialize(data)
        assert isinstance(parsed, ConfigOption)
        assert parsed.configuration["key1"] == "value1"
        assert parsed.configuration["key2"] == "value2"

    def test_empty_config(self):
        option = ConfigOption()
        data = option.serialize()
        parsed, _ = SdOption.deserialize(data)
        assert isinstance(parsed, ConfigOption)
        assert len(parsed.configuration) == 0


class TestSdOptionDeserialize:
    def test_too_short(self):
        with pytest.raises(MessageFormatError, match="too short"):
            SdOption.deserialize(b"\x00\x01")
