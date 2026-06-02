# someip-stack

A complete [SOME/IP](https://www.autosar.org/standards/foundation/) (Scalable service-Oriented MiddlewarE over IP) protocol stack implementation in Python, compatible with specification versions 1.0 through 1.8.0.

## Features

- **Full serialization engine** — all SOME/IP data types with correct alignment: primitives, strings, structs, arrays, dynamic arrays, enums, maps, unions
- **Message format** — 16-byte header, request/response/notification/error message types, multi-version header support
- **Transport** — UDP and TCP transports built on asyncio, SOME/IP-TP segmentation and reassembly for large messages
- **Service Discovery (SD)** — OfferService, FindService, SubscribeEventGroup with SD timer state machine (INITIAL → REPEAT → MAIN phases)
- **Service layer** — Skeleton (server), Proxy (client), Dispatcher, Event, Field (getter/setter/notifier), EventGroup
- **Multi-version** — protocol version as configuration, version-specific behavior (union length prefix v1.1+, TP v1.5+, E2E v1.8.0)
- **Zero runtime dependencies** — Python standard library only
- **Cross-platform** — Windows and Linux (x86)

## Requirements

- Python >= 3.9

## Installation

```bash
pip install -e .
```

For development (includes pytest):

```bash
pip install -e ".[dev]"
```

## Quick Start

### Request / Response

```python
import asyncio
import struct
from someip import Skeleton, Proxy, UdpTransport, Dispatcher
from someip.config.service_config import ServiceInterfaceConfig

# --- Server ---
config = ServiceInterfaceConfig(service_id=0x5000, instance_id=0x0001, interface_version=1)
skeleton = Skeleton(config)

async def add_handler(request):
    a, b = struct.unpack(">II", request.payload[:8])
    return struct.pack(">I", a + b)

skeleton.register_method(0x0001, add_handler)

# --- Client ---
proxy = Proxy(config)
proxy.client_id = 0x0001
request = proxy.build_request(0x0001, struct.pack(">II", 42, 58))
# send via transport, then:
response = await proxy.send_and_wait(request, timeout=3.0)
result = struct.unpack(">I", response.payload)[0]  # 100
```

### Field Access

```python
# Server: register a field with getter and setter
field = skeleton.register_field(0x0100)
field.set_getter_handler(lambda: struct.pack(">f", current_speed))
field.set_setter_handler(set_speed_callback)

# Client: read and write the field
get_req = proxy.build_field_get(0x0100)
set_req = proxy.build_field_set(0x0100, struct.pack(">f", 80.5))
```

### Event Notification

```python
# Server: register and publish an event
event = skeleton.register_event(0x8001)
await event.notify(payload, client_id=0, session_id=1)

# Client: register a notification handler
dispatcher.register_notification_handler(service_id, 0x8001, my_handler)
```

## Architecture

```
┌─────────────────────────────────────┐
│           Application Layer          │  User-defined services and clients
├─────────────────────────────────────┤
│           Service Layer              │  Skeleton / Proxy / Dispatcher / Event / Field
├─────────────────────────────────────┤
│        Service Discovery (SD)        │  SdAgent / SdEntry / SdOption / SD Timer FSM
├─────────────────────────────────────┤
│       Message / Serialization        │  SomeipMessage / SomeipHeader / Codec / Types
├─────────────────────────────────────┤
│          Transport Layer             │  TCP / UDP / SOME/IP-TP
└─────────────────────────────────────┘
```

Each layer depends only on the layer below it.

## Project Structure

```
someip/
├── config/          # Protocol version, service config, stack config
├── types/           # Type system: primitives, strings, containers, codec
├── message/         # SOME/IP header, message, message type, return code, TP
├── transport/       # UDP, TCP transports
├── service/         # Skeleton, Proxy, Dispatcher, Event, Field, EventGroup
├── sd/              # SD agent, entries, options, messages, timer, subscription
├── util/            # Async and network utilities
└── error.py         # Exception hierarchy
```

## Examples

Run each example in two terminals (server first, then client):

```bash
# Simple request/response
python -m examples.simple_service server
python -m examples.simple_service client

# Event subscription
python -m examples.event_subscription server
python -m examples.event_subscription client

# Field getter/setter/notifier
python -m examples.field_access server
python -m examples.field_access client

# Service discovery
python -m examples.sd_discovery server
python -m examples.sd_discovery client
```

## Testing

```bash
pytest tests/ -v
```

175 tests covering all layers: type serialization, message format, transport, service discovery, service layer, and end-to-end integration.

## License

MIT
