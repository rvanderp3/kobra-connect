# kobra-connect

Local LAN API client for Anycubic Kobra 3 / S1 series 3D printers.

Connects directly to your printer over the local network — no cloud services required. Performs the signed MQTT handshake, establishes a mutual-TLS connection, and exposes blocking query methods for temperature, fan speed, printer info, and more.

## Requirements

- Python >=3.9
- Printer must be in **LAN mode** (not cloud mode)
- Both machines on the same network

## Installation

```bash
pip install .
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run kobra-oe --ip 192.168.0.71
```

## Quick Start

### Query-based

```python
from kobra_connect import KobraClient

with KobraClient("192.168.0.71") as client:
    temp = client.query_temperature()
    print(f"Nozzle: {temp.curr_nozzle}°C -> {temp.target_nozzle}°C")
    print(f"Bed:    {temp.curr_bed}°C -> {temp.target_bed}°C")

    info = client.query_info()
    print(f"{info.name} ({info.model}) — firmware {info.firmware}")

    fan = client.query_fan_speed()
    print(f"Part cooling: {fan.part_cooling}%")
```

### Live streaming

```python
from kobra_connect import KobraClient

def on_report(topic, data):
    print(f"[{topic}] {data}")

client = KobraClient("192.168.0.71")
client.connect()
client.on_report = on_report
client.loop_forever()
```

## API Reference

### `KobraClient(host: str)`

Synchronous MQTT client. Supports use as a context manager (`with` statement calls `connect()`/`disconnect()` automatically).

#### Connection

| Method | Description |
|---|---|
| `handshake() -> HandshakeResult` | Perform the LAN handshake to obtain MQTT credentials |
| `connect(timeout=10.0) -> HandshakeResult` | Handshake + connect to the MQTT broker. Raises `HandshakeError` on timeout |
| `disconnect()` | Disconnect from the MQTT broker and clean up temp files |

#### Queries (blocking)

| Method | Returns | Description |
|---|---|---|
| `query(msg_type, timeout=5.0)` | `dict` | Raw query by message type |
| `query_temperature()` | `Temperature` | Nozzle and bed temperatures |
| `query_info()` | `PrinterInfo` | Full printer status including nested `Temperature` and `PrintProject` |
| `query_fan_speed()` | `FanSpeed` | Part cooling, aux, and box fan speeds |

#### Subscriptions

| Method | Description |
|---|---|
| `subscribe_all()` | Subscribe to all report topics (auto-called on connect) |
| `loop_forever()` | Block and process incoming MQTT messages |

#### Callback

Set `client.on_report` to a `Callable[[str, dict], None]` to receive every incoming report as `(topic, data_dict)`.

### `do_handshake(host: str) -> HandshakeResult`

Low-level function that runs the handshake without connecting MQTT. Useful if you want to manage the MQTT connection yourself.

### Exceptions

| Exception | Description |
|---|---|
| `HandshakeError` | Handshake failed (network error, bad response, timeout) |
| `CloudModeError` | Printer is in cloud mode — switch to LAN mode |

## Data Models

All models are frozen (immutable) dataclasses.

### `Temperature`

| Field | Type | Description |
|---|---|---|
| `curr_nozzle` | `float` | Current nozzle temperature (°C) |
| `target_nozzle` | `float` | Target nozzle temperature (°C) |
| `curr_bed` | `float` | Current bed temperature (°C) |
| `target_bed` | `float` | Target bed temperature (°C) |

### `FanSpeed`

| Field | Type | Description |
|---|---|---|
| `part_cooling` | `int` | Part cooling fan speed (%) |
| `aux` | `int` | Auxiliary fan speed (%) |
| `box` | `int` | Box fan level |

### `PrinterInfo`

| Field | Type | Description |
|---|---|---|
| `name` | `str` | User-assigned printer name |
| `model` | `str` | Model name |
| `model_id` | `int` | Numeric model ID |
| `ip` | `str` | Printer IP address |
| `firmware` | `str` | Firmware version |
| `state` | `str` | Printer state |
| `temperature` | `Temperature` | Current temperatures |
| `fan_speed_pct` | `int` | Part cooling fan speed (%) |
| `aux_fan_speed_pct` | `int` | Aux fan speed (%) |
| `box_fan_level` | `int` | Box fan level |
| `print_speed_mode` | `int` | Print speed mode |
| `project` | `PrintProject \| None` | Active print project |
| `features` | `dict` | Printer feature flags |

### `PrintProject`

| Field | Type | Description |
|---|---|---|
| `state` | `str` | Project state (e.g. `"printing"`) |
| `filename` | `str` | File being printed |
| `progress` | `int` | Print progress (%) |
| `curr_layer` | `int` | Current layer |
| `total_layers` | `int` | Total layers |
| `remain_time` | `int` | Remaining time (seconds) |
| `print_time` | `int` | Elapsed print time (seconds) |
| `pause` | `int` | Pause state (see `PauseState`) |

Properties: `is_printing -> bool`, `is_paused -> bool`

### `PauseState(IntEnum)`

| Value | Name |
|---|---|
| 0 | `PRINTING` |
| 1 | `PAUSED` |
| 2 | `PAUSING` |
| 3 | `RESUMING` |
| 4 | `STOPPING` |

### `HandshakeResult`

| Field | Type |
|---|---|
| `broker_host` | `str` |
| `broker_port` | `int` |
| `username` | `str` |
| `password` | `str` |
| `device_id` | `str` |
| `model_id` | `str` |
| `serial` | `str` |
| `device_cert` | `str` |
| `device_key` | `str` |
| `mac` | `str \| None` |
| `model_name` | `str \| None` |
| `device_type` | `str \| None` |

## How It Works

1. **HTTP handshake** — Fetches printer info from port 18910, sends a signed POST request, receives an AES-CBC encrypted payload containing MQTT broker credentials and a device certificate.
2. **MQTT connect** — Connects to the printer's local MQTT broker using mutual TLS (device cert + key).
3. **Query/response** — Publishes a query message to a topic and blocks until the printer responds on the corresponding report topic.

All communication is local — no Anycubic cloud services are involved.

## Development

```bash
uv sync
uv run pytest
```

## OctoEverywhere Companion

The `kobra_connect.octoeverywhere` subpackage connects your Kobra 3 to the [OctoEverywhere](https://octoeverywhere.com) cloud for remote monitoring from the OE dashboard and mobile apps.

### Connect to OctoEverywhere cloud

```bash
uv sync
uv run kobra-oe run --ip 192.168.0.71
```

On first run, you'll see a link URL — open it in your browser to link the printer to your OE account:

```
  Link your printer to OctoEverywhere:

  https://octoeverywhere.com/getstarted?printerid=TM6H8KYMQU2S6FP...
```

After linking, the companion connects your Kobra to OE and serves live printer status.

### Standalone monitoring (no OE cloud)

```bash
uv run kobra-oe monitor --ip 192.168.0.71
```

Or from Python:

```python
from kobra_connect.octoeverywhere.host import KobraHost

host = KobraHost("192.168.0.71")
host.run_standalone()
```

### Programmatic access

```python
from kobra_connect.octoeverywhere.host import KobraHost

host = KobraHost("192.168.0.71")
host.connect()

# Get OE-compatible job status dict
status = host.command_handler.GetCurrentJobStatus()
print(status)

# Get printer state reporter
reporter = host.state_reporter
print(reporter.GetTemps())          # (bed_temp, nozzle_temp)
print(reporter.GetCurrentLayerInfo())  # (current, total)

host.disconnect()
```

### Architecture

```
User's phone/browser
    │ HTTPS
    ▼
OctoEverywhere Cloud
    │ WSS (FlatBuffer protocol)
    ▼
oe_client.py ──► command_router.py ──► KobraClient (MQTT)
                                            │
                                            ▼
                                       Kobra 3 Printer
```

## License

MIT
