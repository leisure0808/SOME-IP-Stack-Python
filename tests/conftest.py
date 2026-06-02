"""Shared test fixtures."""

import pytest
from someip.config.protocol import ProtocolVersion
from someip.types.codec import Codec


@pytest.fixture
def codec_v18():
    """Codec for SOME/IP v1.8.0."""
    return Codec(ProtocolVersion.V1_8_0)


@pytest.fixture
def codec_v10():
    """Codec for SOME/IP v1.0."""
    return Codec(ProtocolVersion.V1_0)
