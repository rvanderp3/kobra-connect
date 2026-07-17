# Anycubic Kobra 3 MQTT Command Reference

## Connection

- **Broker**: `a1mqttxrcwtdv-ats.iot.us-east-1.amazonaws.com` (cloud) or printer IP for LAN mode
- **Port**: `7125` (cloud) or `9883` (LAN mode)
- **TLS**: Mutual TLS with client certificate
- **Auth**: Username/password from Anycubic Slicer Next or device account

## Topic Patterns

All topics use model ID `20024` for Kobra 3 (also `20026` for K3 Max, `20027` for K3 V2, `20025` for KS1, `20029` for KS1 Max).

### Query Topics (commands TO printer)

**From Slicer (recommended for most commands):**
```
anycubic/anycubicCloud/v1/slicer/printer/{model_id}/{device_id}/{endpoint}
```

**From Web:**
```
anycubic/anycubicCloud/v1/web/printer/{model_id}/{device_id}/{endpoint}
```

### Report Topics (responses FROM printer)

```
anycubic/anycubicCloud/v1/printer/public/{model_id}/{device_id}/{endpoint}/report
```

### Subscriptions

```
anycubic/anycubicCloud/v1/printer/public/{model_id}/{device_id}/#
```

## Base Message Format

```json
{
    "type": "<type>",
    "action": "<action>",
    "timestamp": <unix_timestamp_ms>,
    "msgid": "<uuid>",
    "data": { ... }
}
```

---

## 1. Query Printer Info

**Topic:** `anycubic/anycubicCloud/v1/slicer/printer/20024/{device_id}/info`

```json
{
    "type": "info",
    "action": "query",
    "timestamp": 1733257941899,
    "msgid": "747b3bf5-6c54-45a7-97bb-67507d78d160",
    "data": null
}
```

**Response topic:** `anycubic/anycubicCloud/v1/printer/public/20024/{device_id}/info/report`

```json
{
    "type": "info",
    "action": "report",
    "timestamp": 100107,
    "msgid": "747b3bf5-...",
    "state": "done",
    "code": 200,
    "msg": "done",
    "data": {
        "printerName": "My Kobra 3",
        "urls": {
            "fileUploadurl": "http://{ip}:18910/gcode_upload?s=...",
            "rtspUrl": "http://{ip}:18088/flv"
        },
        "model": "Anycubic Kobra 3",
        "ip": "{ip}",
        "version": "2.3.5.3",
        "state": "free",
        "temp": {
            "curr_hotbed_temp": 23,
            "curr_nozzle_temp": 28,
            "target_hotbed_temp": 0,
            "target_nozzle_temp": 0
        },
        "print_speed_mode": 2,
        "fan_speed_pct": 0,
        "aux_fan_speed_pct": 0
    }
}
```

---

## 2. Query Printer Status (during print)

**Topic:** `anycubic/anycubicCloud/v1/slicer/printer/20024/{device_id}/print`

```json
{
    "type": "print",
    "action": "query",
    "timestamp": 1733257941899,
    "msgid": "b2d0a5b0-b1b5-11ef-8e80-67dea82d3a00",
    "data": null
}
```

**Response topic:** `anycubic/anycubicCloud/v1/printer/public/20024/{device_id}/print/report`

---

## 3. Start Print from File on Printer

**Topic (from slicer):** `anycubic/anycubicCloud/v1/slicer/printer/20024/{device_id}/print`
**Topic (from web):** `anycubic/anycubicCloud/v1/web/printer/20024/{device_id}/print`

### Minimal:
```json
{
    "type": "print",
    "action": "start",
    "msgid": "02fd3987-a2ff-244e-7c95-7fe257a9ef70",
    "timestamp": 1660201929871,
    "data": {
        "taskid": "-1",
        "filename": "test_model/FlexibleShark-41m.gcode",
        "filetype": 1
    }
}
```

### Full (with AMS settings):
```json
{
    "type": "print",
    "action": "start",
    "msgid": "02fd3987-a2ff-244e-7c95-7fe257a9ef70",
    "timestamp": 1660201929871,
    "data": {
        "taskid": "-1",
        "filename": "test_model/FlexibleShark-41m.gcode",
        "filepath": "/",
        "filetype": 1,
        "md5": "943c0dff568dd508e21af2d894bb6b49",
        "url": "https://anycubic.com/store/aaa.gcode",
        "project_type": 1,
        "filesize": 188000,
        "task_mode": 1,
        "ams_settings": {
            "use_ams": true,
            "ams_box_mapping": [
                {
                    "paint_index": 0,
                    "ams_index": 0,
                    "paint_color": [255, 255, 255, 255],
                    "ams_color": [255, 255, 255, 255],
                    "material_type": "PLA"
                }
            ]
        },
        "task_settings": {
            "auto_leveling": 0,
            "vibration_compensation": 0,
            "flow_calibration": 0
        }
    }
}
```

**Field notes:**
- `taskid`: `"-1"` for new task, or actual task ID
- `filetype`: `1` = gcode
- `task_mode`: `1` = local file
- `task_settings.auto_leveling`: `0` or `1`
- `task_settings.vibration_compensation`: `0` or `1`
- `task_settings.flow_calibration`: `0` or `1`

---

## 4. Pause Print

**Topic (from slicer or web):** `anycubic/anycubicCloud/v1/slicer/printer/20024/{device_id}/print`

```json
{
    "type": "print",
    "action": "pause",
    "timestamp": 1733257941899,
    "msgid": "b2d0a5b0-b1b5-11ef-8e80-67dea82d3a00",
    "data": {
        "taskid": "-1"
    }
}
```

---

## 5. Resume Print

**Topic (from slicer or web):** `anycubic/anycubicCloud/v1/slicer/printer/20024/{device_id}/print`

```json
{
    "type": "print",
    "action": "resume",
    "timestamp": 1733257941899,
    "msgid": "b2d0a5b0-b1b5-11ef-8e80-67dea82d3a00",
    "data": {
        "taskid": "-1"
    }
}
```

---

## 6. Stop/Cancel Print

**Topic (from slicer or web):** `anycubic/anycubicCloud/v1/slicer/printer/20024/{device_id}/print`

```json
{
    "type": "print",
    "action": "stop",
    "timestamp": 1733337112202,
    "msgid": "07fe2ea0-b26e-11ef-94d0-7925260ebe40",
    "data": {
        "taskid": "-1"
    }
}
```

There is also a `cancel` action (Kobra 2 docs):
```json
{
    "type": "print",
    "action": "cancel",
    "data": {
        "taskid": "-1"
    }
}
```

Note: The Rinkhals/Kobra 3 firmware uses `stop`; the Kobra 2 API docs reference both `stop` and `cancel`.

---

## 7. Set Nozzle Temperature

**Topic (from web):** `anycubic/anycubicCloud/v1/web/printer/20024/{device_id}/print`

```json
{
    "type": "print",
    "action": "update",
    "timestamp": 1733257941899,
    "msgid": "b2d0a5b0-b1b5-11ef-8e80-67dea82d3a00",
    "data": {
        "taskid": "-1",
        "settings": {
            "target_nozzle_temp": 210
        }
    }
}
```

---

## 8. Set Bed Temperature

**Topic (from web):** `anycubic/anycubicCloud/v1/web/printer/20024/{device_id}/print`

```json
{
    "type": "print",
    "action": "update",
    "timestamp": 1733257941899,
    "msgid": "b2d0a5b0-b1b5-11ef-8e80-67dea82d3a00",
    "data": {
        "taskid": "-1",
        "settings": {
            "target_hotbed_temp": 60
        }
    }
}
```

---

## 9. Combined Temperature + Fan + Speed Update

**Topic (from slicer or web):** `anycubic/anycubicCloud/v1/slicer/printer/20024/{device_id}/print`

```json
{
    "type": "print",
    "action": "update",
    "timestamp": 1733257941899,
    "msgid": "b2d0a5b0-b1b5-11ef-8e80-67dea82d3a00",
    "data": {
        "taskid": "0",
        "settings": {
            "target_nozzle_temp": 210,
            "target_hotbed_temp": 60,
            "fan_speed_pct": 100,
            "print_speed_mode": 2,
            "z_comp": 0
        }
    }
}
```

**Settings fields:**
- `target_nozzle_temp`: Nozzle temperature in °C (0 = off)
- `target_hotbed_temp`: Bed temperature in °C (0 = off)
- `fan_speed_pct`: Part cooling fan 0-100
- `print_speed_mode`: `1` = silent, `2` = standard, `3` = fast/sport
- `z_comp`: Z compensation value

---

## 10. Adjust Print Speed

**Topic:** `anycubic/anycubicCloud/v1/web/printer/20024/{device_id}/print`

### Silent:
```json
{
    "type": "print",
    "action": "update",
    "timestamp": 1733258087225,
    "msgid": "096fa290-b1b6-11ef-8e80-67dea82d3a00",
    "data": {
        "taskid": "492102245",
        "settings": {
            "print_speed_mode": 1
        }
    }
}
```

### Standard:
```json
{
    "type": "print",
    "action": "update",
    "timestamp": 1733258087225,
    "msgid": "096fa290-b1b6-11ef-8e80-67dea82d3a00",
    "data": {
        "taskid": "492102245",
        "settings": {
            "print_speed_mode": 2
        }
    }
}
```

### Sport/Fast:
```json
{
    "type": "print",
    "action": "update",
    "timestamp": 1733258087225,
    "msgid": "096fa290-b1b6-11ef-8e80-67dea82d3a00",
    "data": {
        "taskid": "492102245",
        "settings": {
            "print_speed_mode": 3
        }
    }
}
```

---

## 11. Control Camera Light

**Topic:** `anycubic/anycubicCloud/v1/web/printer/20024/{device_id}/light`

### Turn On:
```json
{
    "type": "light",
    "action": "control",
    "timestamp": 1733258023447,
    "msgid": "e36be270-b1b5-11ef-8e80-67dea82d3a00",
    "data": {
        "type": 3,
        "status": 1,
        "brightness": 100
    }
}
```

### Turn Off:
```json
{
    "type": "light",
    "action": "control",
    "timestamp": 1733257985156,
    "msgid": "cc992440-b1b5-11ef-8e80-67dea82d3a00",
    "data": {
        "type": 3,
        "status": 0,
        "brightness": 0
    }
}
```

**Light types:**
- `type: 3` = Camera light
- `type: 1` = Head light (may not apply to KS1)
- `type: 2` = Chamber light (KS1/S1 only)

---

## 12. Turn Head Light On/Off

**Topic:** `anycubic/anycubicCloud/v1/web/printer/20024/{device_id}/light`

### On:
```json
{
    "type": "light",
    "action": "control",
    "timestamp": 1733258054565,
    "msgid": "f5f81d50-b1b5-11ef-8e80-67dea82d3a00",
    "data": {
        "type": 1,
        "status": 1,
        "brightness": 100
    }
}
```

### Off:
```json
{
    "type": "light",
    "action": "control",
    "timestamp": 1733258054565,
    "msgid": "f5f81d50-b1b5-11ef-8e80-67dea82d3a00",
    "data": {
        "type": 1,
        "status": 0,
        "brightness": 0
    }
}
```

---

## 13. List Files on Printer

**Topic:** `anycubic/anycubicCloud/v1/slicer/printer/20024/{device_id}/file`

### List internal files:
```json
{
    "type": "file",
    "action": "listLocal",
    "timestamp": 1733257941899,
    "msgid": "b2d0a5b0-b1b5-11ef-8e80-67dea82d3a00",
    "data": {
        "path": "/"
    }
}
```

### List USB files:
```json
{
    "type": "file",
    "action": "listUdisk",
    "timestamp": 1733257941899,
    "msgid": "b2d0a5b0-b1b5-11ef-8e80-67dea82d3a00",
    "data": {
        "path": "/"
    }
}
```

---

## 14. Delete File

### Delete internal file:
```json
{
    "type": "file",
    "action": "deleteLocal",
    "timestamp": 1733257941899,
    "msgid": "b2d0a5b0-b1b5-11ef-8e80-67dea82d3a00",
    "data": {
        "path": "dir",
        "filename": "filename"
    }
}
```

### Delete USB file:
```json
{
    "type": "file",
    "action": "deleteUdisk",
    "timestamp": 1733257941899,
    "msgid": "b2d0a5b0-b1b5-11ef-8e80-67dea82d3a00",
    "data": {
        "path": "dir",
        "filename": "filename"
    }
}
```

---

## 15. Get Slice Parameters

```json
{
    "type": "print",
    "action": "getSliceParam",
    "timestamp": 1733257941899,
    "msgid": "b2d0a5b0-b1b5-11ef-8e80-67dea82d3a00",
    "data": null
}
```

---

## 16. Upload File to Printer (via HTTP)

Upload gcode files via HTTP POST:
```
http://{printer_ip}:18910/gcode_upload?s={upload_token}
```

The upload token is returned in the `info` report under `urls.fileUploadurl`.

---

## G-code Commands (via MQTT)

**There is no documented MQTT "send gcode" command type.** The Anycubic MQTT protocol does not appear to expose a direct G-code injection interface. Instead, commands are implemented as specific `type`/`action` pairs (like `type: "print", action: "pause"`).

For raw G-code control (including **homing**), you would need to:

1. **Use Rinkhals firmware** (custom firmware for Kobra 3) which exposes a local Moonraker API with Klipper, enabling direct G-code via:
   ```
   http://{printer_ip}:7125/printer/gcode/script?script=G28
   ```
   Or via the local MQTT broker on port `2883` with fixed credentials.

2. **Use Klipper Moonraker API** (if running Rinkhals):
   ```
   POST http://{printer_ip}:7125/printer/gcode/script
   Content-Type: application/json
   {"script": "G28"}       # Home all axes
   {"script": "G28 X Y"}   # Home X and Y only
   {"script": "M104 S210"} # Set nozzle temp (no wait)
   {"script": "M140 S60"}  # Set bed temp (no wait)
   {"script": "M109 S210"} # Wait for nozzle temp
   {"script": "M190 S60"}  # Wait for bed temp
   ```

---

## Important Notes

1. **Timestamp**: Use millisecond Unix timestamps
2. **msgid**: Use UUID v4 format
3. **taskid**: `"-1"` for new tasks; specific task IDs for ongoing prints
4. **print_speed_mode**: `1`=silent, `2`=standard, `3`=fast
5. **filetype**: `1` = gcode
6. **task_mode**: `1` = local file on printer
7. **Slicer vs Web topic**: Some commands (start print) must use the `slicer` topic; temperature/fan updates can use either
8. **Cloud vs LAN**: The same protocol works for both cloud (port 7125 with Anycubic broker) and LAN mode (port 9883 with local broker)
9. **Token requirement**: MQTT live updates require tokens from Anycubic Slicer Next, not web tokens

## Key Repositories

- **Rinkhals** (custom firmware with MQTT docs): https://github.com/jbatonnet/Rinkhals - Full MQTT documentation at `docs/docs/firmware/mqtt.md`
- **hass-anycubic_cloud** (Home Assistant): https://github.com/Nino6689/hass-anycubic_cloud
- **anycubic_ha_local** (local LAN HA): https://github.com/chrisfore/anycubic_ha_local
- **Anycubic Kobra 2 Tools** (MQTT API docs): https://github.com/1coderookie/Anycubic-Kobra-2-Series-Tools
- **anycubic_kobrax** (Kobra X LAN): https://github.com/stribor/anycubic_kobrax
- **anycubic-s1-mqtt-bridge**: https://github.com/metheos/anycubic-s1-mqtt-bridge
