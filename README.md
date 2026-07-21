# kobra-connect

Local LAN API client for Anycubic Kobra 3 / S1 series 3D printers.

Connects directly to your printer over the local network — no cloud services required, no custom firmware needed. Performs the signed MQTT handshake, establishes a mutual-TLS connection, and exposes blocking query methods for temperature, fan speed, printer info, and more.

## Requirements

- Python >=3.9
- Printer must be in **LAN mode** (not cloud mode)
- Both machines on the same network
- **Stock firmware** — no custom firmware, rooted printer, or Anycubic cloud services required

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

### Sending commands

```python
with KobraClient("192.168.0.71") as client:
    client.command_pause()
    client.command_resume()
    client.command_cancel()
    client.command_set_temperature(nozzle=210, bed=60)
    client.command_set_fan(speed_pct=100)
    client.command_start_print("/storage/some_file.gcode")
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

#### Commands (fire-and-forget)

| Method | Description |
|---|---|
| `command_pause()` | Pause the current print |
| `command_resume()` | Resume a paused print |
| `command_cancel()` | Cancel the current print |
| `command_start_print(filename)` | Start printing a file on the printer |
| `command_set_temperature(nozzle, bed)` | Set nozzle and/or bed target temperature |
| `command_set_fan(speed_pct)` | Set part cooling fan speed (0–100) |
| `command_set_speed_mode(mode)` | Set print speed mode |
| `command_list_files(path)` | List files on the printer's storage |

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
| `state` | `str` | Project state (e.g. `"printing"`, `"finish"`) |
| `filename` | `str` | File being printed |
| `progress` | `int` | Print progress (%) |
| `curr_layer` | `int` | Current layer |
| `total_layers` | `int` | Total layers |
| `remain_time` | `int` | Remaining time (minutes from printer, converted to seconds) |
| `print_time` | `int` | Elapsed print time (minutes from printer, converted to seconds) |
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

### Handshake and Connection

1. **HTTP handshake** — Fetches printer info from port 18910, sends a signed POST request, receives an AES-CBC encrypted payload containing MQTT broker credentials and a device certificate.
2. **MQTT connect** — Connects to the printer's local MQTT broker (port 9883, TLS) using the device certificate and key for mutual authentication.
3. **Query/response** — Publishes a query message to a topic and blocks until the printer responds on the corresponding report topic.

### MQTT Protocol

The Kobra 3 uses an Anycubic-proprietary MQTT protocol over TLS. All communication is local — no Anycubic cloud services are involved.

**Topics:**

| Direction | Topic pattern | Purpose |
|---|---|---|
| Query | `anycubic/anycubicCloud/v1/printer/public/{model_id}/{device_id}/info` | Request printer info |
| Query | `anycubic/anycubicCloud/v1/printer/public/{model_id}/{device_id}/tempature` | Request temperatures |
| Query | `anycubic/anycubicCloud/v1/printer/public/{model_id}/{device_id}/fan` | Request fan speeds |
| Report | `anycubic/anycubicCloud/v1/printer/public/{model_id}/{device_id}/info/report` | Info broadcast |
| Report | `anycubic/anycubicCloud/v1/printer/public/{model_id}/{device_id}/tempature/report` | Temperature broadcast |
| Report | `anycubic/anycubicCloud/v1/printer/public/{model_id}/{device_id}/fan/report` | Fan speed broadcast |
| Command | `anycubic/anycubicCloud/v1/slicer/printer/{model_id}/{device_id}/print` | Print commands (pause/resume/cancel/start) |
| Command | `anycubic/anycubicCloud/v1/slicer/printer/{model_id}/{device_id}/file` | File operations |
| Command | `anycubic/anycubicCloud/v1/slicer/printer/{model_id}/{device_id}/light` | Light control |

**Command format:**

```json
{
  "msgid": "<uuid>",
  "data": {
    "did": "<device_id>",
    "bid": "<model_id>",
    "type": "print",
    "action": "pause",
    "data": {"taskid": "-1"}
  }
}
```

### Known Limitations

- **No toolhead position data** — The MQTT protocol does not expose X/Y/Z coordinates. The `toolhead` and `gcode_move` Moonraker objects return zeros.
- **Time values in minutes** — The printer reports `print_time` and `remain_time` in minutes, not seconds. This library converts to seconds automatically.
- **Print state source** — Use `project.state` (e.g. `"printing"`, `"finish"`) for print status, not `info.state` (which reflects printer-level state).
- **No raw G-code passthrough** — Commands use typed MQTT actions (`print`, `file`, `light`), not raw G-code. The bridge translates Moonraker G-code commands into the appropriate MQTT actions.
- **Filament usage not available** — The printer does not report filament length consumed.

## Moonraker Bridge

The `kobra_connect.moonraker_bridge` subpackage implements a [Moonraker](https://moonraker.readthedocs.io/)-compatible API server, enabling integration with Fluidd, Mainsail, and OctoEverywhere.

### Features

- Moonraker HTTP + WebSocket JSON-RPC API
- Fluidd v1.37.2 web interface served from the bridge
- Klipper-compatible printer object model (extruder, heater_bed, gcode_move, toolhead, print_stats, etc.)
- Real-time temperature history (ring buffer)
- File listing from printer storage
- Webcam proxy (MJPEG stream/snapshot from an IP camera)
- OctoEverywhere cloud companion support
- **Backup/restore of OctoEverywhere credentials and printer linking**

### Running the Bridge

```bash
# Direct
uv run python -m kobra_connect.moonraker_bridge --ip 192.168.0.71

# With Fluidd
uv run python -m kobra_connect.moonraker_bridge --ip 192.168.0.71 --fluidd-path ./fluidd

# With webcam proxy
uv run python -m kobra_connect.moonraker_bridge \
  --ip 192.168.0.71 \
  --webcam-url http://192.168.0.35
```

### Moonraker API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/server/info` | GET | Server info |
| `/server/config` | GET | Server config |
| `/server/temperature_store` | GET | Temperature history |
| `/server/files/list` | GET | Files on printer |
| `/printer/info` | GET | Printer info |
| `/printer/objects/list` | GET | Available printer objects |
| `/printer/objects/query` | POST | Query printer object fields |
| `/printer/objects/subscribe` | POST | Subscribe to object updates |
| `/printer/gcode/script` | POST | Execute G-code (translated to MQTT commands) |
| `/printer/print/start` | POST | Start a print |
| `/printer/print/pause` | POST | Pause current print |
| `/printer/print/resume` | POST | Resume paused print |
| `/printer/print/cancel` | POST | Cancel current print |
| `/printer/emergency_stop` | POST | Emergency stop |
| `/websocket` | WS | WebSocket for real-time updates |

### Supported Moonraker Objects

| Object | Fields |
|---|---|
| `extruder` | temperature, target, pressure_advance, smooth_time |
| `heater_bed` | temperature, target |
| `gcode_move` | speed, speed_factor, absolute_coord, position |
| `toolhead` | position |
| `print_stats` | state, filename, total_duration, print_duration, layer_count, message |
| `display_status` | progress, message |
| `fan` | speed |
| `heater_fan hotend_fan` | speed |
| `controller_fan` | speed |
| `idle_timeout` | state, time |

### OctoEverywhere Integration

The bridge exposes a Klipper-compatible Moonraker API that OctoEverywhere connects to:

```
User's phone/browser
    │ HTTPS
    ▼
OctoEverywhere Cloud
    │ WSS (FlatBuffer protocol)
    ▼
oe_client.py ──► command_router.py ──► Moonraker Bridge (port 7125)
                                            │ MQTT
                                            ▼
                                       Kobra 3 Printer
```

**Docker deployment:**

```bash
# Build and start all services
make build
make start

# Link to OctoEverywhere (check logs for link code)
make logs-oe

# View bridge logs
make logs-bridge
```

This runs three containers:
- `kobra-moonraker-bridge` — Moonraker API + Fluidd on port 7125
- `kobra-nginx` — Nginx reverse proxy on port 8080 (host network)
- `octoeverywhere-kobra` — OE companion (host network, connects to bridge at 127.0.0.1:7125)

### Backup & Restore

```bash
# Create timestamped backup of OctoEverywhere data (credentials, link status)
make backup

# List available backups
make list-backups

# Restore Kobra OctoEverywhere data
make restore BACKUP_FILE=/path/to/backup.tar.gz

# Restore Bambu OctoEverywhere data (if using Bambu Connect)
make restore-bambu BACKUP_FILE=/path/to/backup.tar.gz
```

Backups include the printer's OctoEverywhere credentials, so after restore you don't need to re-link.

## Development

```bash
uv sync
uv run pytest
```

## License

Apache-2.0
