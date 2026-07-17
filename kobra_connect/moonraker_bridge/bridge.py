"""Main bridge: Kobra MQTT -> Moonraker API emulation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from typing import Any

from aiohttp import web
import aiohttp

from ..client import KobraClient
from ..models import PrinterInfo, Temperature
from .state import MoonrakerState

logger = logging.getLogger(__name__)

JSONRPC_VERSION = "2.0"
WS_HEARTBEAT_INTERVAL = 30


class JsonRpcResponse:
    def __init__(self, msg_id: int | str | None, result: Any = None, error: dict | None = None):
        self.id = msg_id
        self.result = result
        self.error = error

    def to_json(self) -> str:
        if self.error:
            return json.dumps({"jsonrpc": JSONRPC_VERSION, "id": self.id, "error": self.error})
        return json.dumps({"jsonrpc": JSONRPC_VERSION, "id": self.id, "result": self.result})


def _parse_gcode_to_kobra(script: str) -> list[dict[str, Any]]:
    """Parse G-code commands into Kobra MQTT settings updates.

    Returns a list of Kobra update payloads.  Unsupported G-codes are skipped
    (the caller should still return "ok" so Fluidd does not error out).
    """
    updates: list[dict[str, Any]] = {}
    for line in script.strip().splitlines():
        line = line.split(";")[0].strip()  # strip comments
        if not line:
            continue
        m = re.match(r"([GM]\d+)(.*)", line, re.IGNORECASE)
        if not m:
            continue
        cmd = m.group(1).upper()
        args_str = m.group(2).strip()
        args: dict[str, float] = {}
        for token in re.findall(r"([A-Z])([-\d.]+)", args_str, re.IGNORECASE):
            args[token[0].upper()] = float(token[1])

        if cmd in ("M104", "M109"):  # set nozzle temp
            updates.setdefault("settings", {})["target_nozzle_temp"] = int(args.get("S", 0))
        elif cmd in ("M140", "M190"):  # set bed temp
            updates.setdefault("settings", {})["target_hotbed_temp"] = int(args.get("S", 0))
        elif cmd == "M106":  # fan on
            pct = int(args.get("S", 255) / 255 * 100)
            updates.setdefault("settings", {})["fan_speed_pct"] = pct
        elif cmd == "M107":  # fan off
            updates.setdefault("settings", {})["fan_speed_pct"] = 0

    if updates:
        return [updates]
    return []


class KobraMoonrakerBridge:
    """Bridges Kobra MQTT client to Moonraker-compatible JSON-RPC API."""

    def __init__(self, host: str, port: int = 7125, webcam_url: str = None):
        self.host = host
        self.port = port
        self.webcam_url = webcam_url or "http://192.168.0.35"
        self._kobra: KobraClient | None = None
        self._state = MoonrakerState()
        self._ws_clients: set[web.WebSocketResponse] = set()
        self._ws_lock = threading.Lock()
        self._ws_subscriptions: dict[int, set[str]] = {}  # connection_id -> subscribed objects
        self._ws_ready: set[int] = set()  # connections that have received klippy_ready
        self._next_conn_id = 1
        self._running = False
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._server_loop: asyncio.AbstractEventLoop | None = None
        self._server_thread: threading.Thread | None = None

    # -- Public API ------------------------------------------------------------

    def start(self) -> None:
        """Start the bridge: connect to Kobra, start HTTP/WS server."""
        logger.info("Starting Kobra Moonraker Bridge on %s:%d", self.host, self.port)

        # 1. Connect to Kobra printer
        self._kobra = KobraClient(self.host)
        self._kobra.connect()
        self._kobra.on_report = self._on_kobra_report
        self._kobra.subscribe_all()

        # 2. Query initial state
        self._refresh_state()

        # 3. Start HTTP/WS server
        self._start_server()

        self._running = True
        logger.info("Bridge started successfully")

    def stop(self) -> None:
        """Stop the bridge."""
        logger.info("Stopping bridge...")
        self._running = False

        if self._kobra:
            self._kobra.disconnect()
            self._kobra = None

        if self._runner and self._server_loop:
            # Schedule cleanup on the server's event loop
            asyncio.run_coroutine_threadsafe(self._runner.cleanup(), self._server_loop)

        if self._server_thread:
            self._server_thread.join(timeout=2.0)

        logger.info("Bridge stopped")

    # -- Kobra MQTT Callback ---------------------------------------------------

    def _on_kobra_report(self, topic: str, data: dict) -> None:
        """Handle incoming Kobra MQTT report and update state."""
        try:
            msg_type = data.get("type", "")
            report_data = data.get("data", data)

            if msg_type == "info" or "/info/report" in topic:
                self._update_from_info(report_data)
            elif msg_type == "tempature" or "/tempature/report" in topic:
                self._update_from_temperature(report_data)
            elif msg_type == "fan" or "/fan/report" in topic:
                self._update_from_fan(report_data)

            # Notify WS clients of status update
            self._broadcast_status_update()

        except Exception as e:
            logger.error("Error processing Kobra report: %s", e, exc_info=True)

    def _update_from_info(self, data: dict) -> None:
        """Update state from info report."""
        # If already a PrinterInfo object, use it directly
        if isinstance(data, PrinterInfo):
            info = data
        else:
            info = PrinterInfo.from_dict(data.get("data", data))
        self._state.update_from_kobra_info(info)

    def _update_from_temperature(self, data: dict) -> None:
        """Update state from temperature report."""
        # If already a Temperature object, use it directly
        if isinstance(data, Temperature):
            temp = data
        else:
            temp = Temperature.from_dict(data.get("data", data))
        self._state.update_from_kobra_temperature(temp)

    def _update_from_fan(self, data: dict) -> None:
        """Update state from fan report (not mapped to Moonraker objects yet)."""
        pass

    def _refresh_state(self) -> None:
        """Query initial state from Kobra."""
        if not self._kobra:
            return
        try:
            info = self._kobra.query_info()
            self._update_from_info(info)
            temp = self._kobra.query_temperature()
            self._update_from_temperature(temp)
        except Exception as e:
            logger.warning("Failed to refresh initial state: %s", e)

    # -- HTTP/WebSocket Server -------------------------------------------------

    def _start_server(self) -> None:
        """Start the aiohttp server in background thread."""
        self._app = web.Application()
        self._app.router.add_get("/websocket", self._handle_websocket)
        # Printer object endpoints
        self._app.router.add_post("/printer/objects/query", self._handle_query)
        self._app.router.add_post("/printer/objects/subscribe", self._handle_subscribe)
        self._app.router.add_get("/printer/objects/list", self._handle_list)
        # Printer info
        self._app.router.add_get("/printer/info", self._handle_printer_info_rest)
        # G-code and print control
        self._app.router.add_post("/printer/gcode/script", self._handle_gcode_script)
        self._app.router.add_get("/printer/gcode/help", self._handle_gcode_help)
        self._app.router.add_post("/printer/print/start", self._handle_print_start)
        self._app.router.add_post("/printer/print/pause", self._handle_print_pause)
        self._app.router.add_post("/printer/print/resume", self._handle_print_resume)
        self._app.router.add_post("/printer/print/cancel", self._handle_print_cancel)
        self._app.router.add_post("/printer/emergency_stop", self._handle_emergency_stop)
        self._app.router.add_post("/printer/firmware_restart", self._handle_firmware_restart)
        # Server endpoints
        self._app.router.add_get("/server/info", self._handle_server_info)
        self._app.router.add_get("/server/config", self._handle_server_config)
        self._app.router.add_get("/server/temperature_store", self._handle_temperature_store)
        self._app.router.add_get("/server/files/list", self._handle_files_list)
        self._app.router.add_get("/server/files/directory", self._handle_files_directory)
        self._app.router.add_post("/server/files/upload", self._handle_files_upload)
        # Auth
        self._app.router.add_get("/access/oneshot_token", self._handle_oneshot_token)
        self._app.router.add_get("/access/info", self._handle_access_info)
        # Machine endpoints
        self._app.router.add_get("/machine/system_info", self._handle_system_info)
        # Webcam endpoints
        self._app.router.add_get("/webcam/", self._handle_webcam)
        self._app.router.add_get("/webcam/stream", self._handle_webcam_stream)
        self._app.router.add_get("/webcam/snapshot", self._handle_webcam_snapshot)
        self._app.router.add_get("/server/webcams/list", self._handle_server_webcams_list)
        self._app.router.add_get("/server/webcams/item", self._handle_server_webcams_item)

        def run_server():
            loop = asyncio.new_event_loop()
            self._server_loop = loop
            asyncio.set_event_loop(loop)

            async def startup():
                self._runner = web.AppRunner(self._app)
                await self._runner.setup()
                site = web.TCPSite(self._runner, "0.0.0.0", self.port)
                await site.start()
                logger.info("HTTP/WS server listening on 0.0.0.0:%d", self.port)

            loop.run_until_complete(startup())
            loop.run_forever()

        import threading
        self._server_thread = threading.Thread(target=run_server, daemon=True, name="moonraker-bridge-server")
        self._server_thread.start()
        # Give server time to start
        time.sleep(0.5)

    # -- WebSocket Handler -----------------------------------------------------

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=WS_HEARTBEAT_INTERVAL)
        await ws.prepare(request)

        with self._ws_lock:
            self._ws_clients.add(ws)

        conn_id = self._next_conn_id
        self._next_conn_id += 1
        self._ws_subscriptions[conn_id] = set()

        logger.info("WebSocket client connected: %s (conn_id=%d)", request.remote, conn_id)

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self._handle_ws_message(ws, msg.data, conn_id)
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error("WS error: %s", ws.exception())
        finally:
            with self._ws_lock:
                self._ws_clients.discard(ws)
            self._ws_subscriptions.pop(conn_id, None)
            logger.info("WebSocket client disconnected: %s (conn_id=%d)", request.remote, conn_id)

        return ws

    async def _handle_ws_message(self, ws: web.WebSocketResponse, data: str, conn_id: int) -> None:
        """Handle incoming WebSocket JSON-RPC message."""
        try:
            msg = json.loads(data)
            msg_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {})

            logger.debug("WS recv: %s (id=%s)", method, msg_id)

            # Handle as request (expects response)
            if msg_id is not None:
                result = await self._dispatch_jsonrpc(method, params, conn_id)
                await ws.send_str(JsonRpcResponse(msg_id, result).to_json())
                # After identify completes, send klippy lifecycle notifications
                if method == "server.connection.identify":
                    await self._send_klippy_ready_to(ws)
            else:
                # Notification (no response)
                await self._dispatch_jsonrpc(method, params, conn_id)

        except json.JSONDecodeError:
            logger.warning("Invalid JSON from WS: %s", data)
        except Exception as e:
            logger.error("WS message handler error: %s", e, exc_info=True)
            if msg_id is not None:
                await ws.send_str(JsonRpcResponse(msg_id, error={"code": -32603, "message": str(e)}).to_json())

    async def _dispatch_jsonrpc(self, method: str, params: dict, conn_id: int = 0) -> Any:
        """Dispatch JSON-RPC method to handler."""
        handlers = {
            # Connection
            "server.connection.identify": self._rpc_connection_identify,
            # Server
            "server.info": self._rpc_server_info,
            "server.config": self._rpc_server_config,
            "server.temperature_store": self._rpc_temperature_store,
            "server.files.list": self._rpc_files_list,
            "server.files.metadata": self._rpc_files_metadata,
            "server.webcams.list": self._rpc_server_webcams_list,
            # Printer
            "printer.info": self._rpc_printer_info,
            "printer.objects.query": self._rpc_query,
            "printer.objects.subscribe": self._rpc_subscribe,
            "printer.objects.list": self._rpc_list,
            "printer.gcode.script": self._rpc_gcode_script,
            "printer.gcode.help": self._rpc_gcode_help,
            "printer.print.start": self._rpc_print_start,
            "printer.print.pause": self._rpc_print_pause,
            "printer.print.resume": self._rpc_print_resume,
            "printer.print.cancel": self._rpc_print_cancel,
            "printer.emergency_stop": self._rpc_emergency_stop,
            "printer.firmware_restart": self._rpc_firmware_restart,
        }

        handler = handlers.get(method)
        if not handler:
            logger.debug("Method not found: %s", method)
            return {"error": {"code": -32601, "message": f"Method not found: {method}"}}

        try:
            # Pass conn_id where needed
            if method == "server.connection.identify":
                return await handler(params, conn_id)
            elif method == "printer.objects.subscribe":
                return await handler(params, conn_id)
            else:
                return await handler(params)
        except Exception as e:
            logger.error("RPC %s failed: %s", method, e, exc_info=True)
            return {"error": {"code": -32603, "message": str(e)}}

    # -- JSON-RPC Handlers -----------------------------------------------------

    async def _rpc_connection_identify(self, params: dict, conn_id: int) -> dict:
        """Handle server.connection.identify"""
        client_name = params.get("client_name", "unknown")
        client_version = params.get("version", "unknown")
        logger.info("Client identified: %s v%s (conn_id=%d)", client_name, client_version, conn_id)
        return {"connection_id": conn_id}

    async def _send_klippy_ready_to(self, ws: web.WebSocketResponse) -> None:
        """Send notify_klippy_connected + notify_klippy_ready to a WS client."""
        try:
            await ws.send_json({
                "jsonrpc": JSONRPC_VERSION,
                "method": "notify_klippy_connected",
                "params": {}
            })
            await ws.send_json({
                "jsonrpc": JSONRPC_VERSION,
                "method": "notify_klippy_ready",
                "params": {}
            })
        except Exception as e:
            logger.warning("Failed to send klippy_ready: %s", e)

    async def _rpc_query(self, params: dict) -> dict:
        """Handle printer.objects.query"""
        objects = params.get("objects", {})
        result = self._state.to_query_result(objects)
        result["eventtime"] = time.time()
        return result

    async def _rpc_subscribe(self, params: dict, conn_id: int = 0) -> dict:
        """Handle printer.objects.subscribe"""
        objects = params.get("objects", {})
        # Track which objects this connection subscribed to
        if conn_id:
            self._ws_subscriptions[conn_id] = set(objects.keys())
        result = self._state.to_subscribe_result(objects)
        result["eventtime"] = time.time()
        return result

    async def _rpc_list(self, params: dict) -> dict:
        """Handle printer.objects.list"""
        return {
            "objects": [
                "webhooks", "print_stats", "virtual_sdcard",
                "extruder", "heater_bed", "gcode_move", "toolhead"
            ]
        }

    async def _rpc_printer_info(self, params: dict) -> dict:
        """Handle printer.info"""
        state = self._state.webhooks.state
        state_message = self._state.webhooks.state_message
        return {
            "state": state,
            "state_message": state_message,
            "hostname": self.host,
            "software_version": f"kobra-connect-0.2.0",
            "cpu_info": "ARM Cortex-A53",
            "cpu_count": 4,
            "cpu_usage": [0.0] * 4,
            "memory_total": 1024 * 1024 * 1024,
            "memory_usage": 0,
            "network": {"rx_bytes": 0, "tx_bytes": 0},
            "moonraker_version": "0.2.0-kobra",
            "api_version": [1, 0, 0],
            "api_version_string": "1.0.0",
        }

    async def _rpc_gcode_script(self, params: dict) -> str:
        """Handle printer.gcode.script — map common G-codes to Kobra MQTT commands."""
        script = params.get("script", "")
        logger.info("G-code script requested: %s", script[:200])

        if not self._kobra:
            logger.warning("No Kobra client connected, ignoring G-code")
            return "ok"

        # Parse G-code into Kobra settings updates
        updates_list = _parse_gcode_to_kobra(script)
        for updates in updates_list:
            settings = updates.get("settings", {})
            if settings:
                try:
                    self._kobra.command_set_temperature(
                        nozzle=settings.get("target_nozzle_temp"),
                        bed=settings.get("target_hotbed_temp"),
                    )
                except Exception as e:
                    logger.warning("Failed to set temperature via MQTT: %s", e)
                try:
                    if "fan_speed_pct" in settings:
                        self._kobra.command_set_fan(settings["fan_speed_pct"])
                except Exception as e:
                    logger.warning("Failed to set fan via MQTT: %s", e)

        return "ok"

    async def _rpc_gcode_help(self, params: dict) -> dict:
        """Handle printer.gcode.help"""
        return {
            "G28": "Home all axes",
            "G1": "Linear move",
            "M104": "Set nozzle temperature",
            "M140": "Set bed temperature",
            "M106": "Set fan speed",
            "M107": "Turn fan off",
            "M109": "Wait for nozzle temperature",
            "M190": "Wait for bed temperature",
        }

    async def _rpc_print_start(self, params: dict) -> str:
        """Handle printer.print.start"""
        filename = params.get("filename", "")
        logger.info("Print start requested: %s", filename)
        if self._kobra:
            try:
                self._kobra.command_start_print(filename)
            except Exception as e:
                logger.error("Failed to start print: %s", e)
        return "ok"

    async def _rpc_print_pause(self, params: dict) -> str:
        """Handle printer.print.pause"""
        logger.info("Print pause requested")
        if self._kobra:
            try:
                self._kobra.command_pause()
            except Exception as e:
                logger.error("Failed to pause: %s", e)
        return "ok"

    async def _rpc_print_resume(self, params: dict) -> str:
        """Handle printer.print.resume"""
        logger.info("Print resume requested")
        if self._kobra:
            try:
                self._kobra.command_resume()
            except Exception as e:
                logger.error("Failed to resume: %s", e)
        return "ok"

    async def _rpc_print_cancel(self, params: dict) -> str:
        """Handle printer.print.cancel"""
        logger.info("Print cancel requested")
        if self._kobra:
            try:
                self._kobra.command_cancel()
            except Exception as e:
                logger.error("Failed to cancel: %s", e)
        return "ok"

    async def _rpc_emergency_stop(self, params: dict) -> str:
        """Handle printer.emergency_stop"""
        logger.warning("Emergency stop requested!")
        if self._kobra:
            try:
                self._kobra.command_cancel()
            except Exception as e:
                logger.error("Failed to emergency stop: %s", e)
        return "ok"

    async def _rpc_firmware_restart(self, params: dict) -> str:
        """Handle printer.firmware_restart"""
        logger.warning("Firmware restart requested!")
        return "ok"

    async def _rpc_server_info(self, params: dict) -> dict:
        """Handle server.info"""
        # klippy_state reflects Klipper's connection state, NOT the print state.
        # OE only accepts: ready, startup, error, shutdown, initializing, disconnected
        webhooks_state = self._state.webhooks.state
        if webhooks_state in ("error",):
            klippy_state = "error"
        else:
            klippy_state = "ready"
        return {
            "klippy_state": klippy_state,
            "klippy_connected": True,
            "hostname": "kobra-connect",
            "software_version": "0.2.0",
            "moonraker_version": "0.2.0-kobra",
            "api_version": [1, 0, 0],
            "api_version_string": "1.0.0",
            "components": [
                "server",
                "file_manager",
                "machine",
            ],
            "invalid_parts": [],
        }

    async def _rpc_server_config(self, params: dict) -> dict:
        """Handle server.config"""
        return {
            "config": {
                "authorization": {
                    "trusted_clients": ["*"],
                    "allowed_services": [],
                },
                "octoprint_compat": {},
                "file_manager": {
                    "enable_object_processing": False,
                },
                "machine": {},
            }
        }

    async def _rpc_temperature_store(self, params: dict) -> dict:
        """Handle server.temperature_store"""
        return self._state.temperature_store.to_dict()

    async def _rpc_files_list(self, params: dict) -> dict:
        """Handle server.files.list"""
        root = params.get("root", "gcodes")
        if root == "gcodes":
            files = self._get_kobra_files()
            return {"files": files}
        return {"files": []}

    async def _rpc_files_metadata(self, params: dict) -> dict:
        """Handle server.files.metadata"""
        filename = params.get("filename", "")
        return {
            "size": 0,
            "modified": 0,
            "filename": filename,
            "gcode_start": "",
            "gcode_end": "",
            "layer_count": 0,
            "layer_height": 0.2,
            "first_layer_height": 0.2,
            "object_height": 0,
            "filament_total": 0,
            "estimated_time": 0,
            "print_duration": 0,
            "filament_used": 0,
        }

    def _get_kobra_files(self) -> list[dict]:
        """List files from Kobra printer (cached briefly)."""
        if not self._kobra:
            return []
        try:
            files = self._kobra.command_list_files(timeout=5.0)
            return [
                {
                    "filename": f.get("name", ""),
                    "size": f.get("size", 0),
                    "modified": f.get("modify_time", 0),
                    "uuid": f.get("url", ""),
                }
                for f in files
            ]
        except Exception as e:
            logger.warning("Failed to list Kobra files: %s", e)
            return []

    # -- HTTP Handlers (for REST API compatibility) ----------------------------

    async def _handle_query(self, request: web.Request) -> web.Response:
        params = await request.json()
        result = await self._rpc_query(params)
        return web.json_response({"result": result})

    async def _handle_subscribe(self, request: web.Request) -> web.Response:
        params = await request.json()
        result = await self._rpc_subscribe(params)
        return web.json_response({"result": result})

    async def _handle_list(self, request: web.Request) -> web.Response:
        result = await self._rpc_list({})
        return web.json_response({"result": result})

    async def _handle_printer_info_rest(self, request: web.Request) -> web.Response:
        result = await self._rpc_printer_info({})
        return web.json_response({"result": result})

    async def _handle_gcode_script(self, request: web.Request) -> web.Response:
        params = await request.json()
        result = await self._rpc_gcode_script(params)
        return web.json_response({"result": result})

    async def _handle_gcode_help(self, request: web.Request) -> web.Response:
        result = await self._rpc_gcode_help({})
        return web.json_response({"result": result})

    async def _handle_print_start(self, request: web.Request) -> web.Response:
        params = await request.json()
        result = await self._rpc_print_start(params)
        return web.json_response({"result": result})

    async def _handle_print_pause(self, request: web.Request) -> web.Response:
        result = await self._rpc_print_pause({})
        return web.json_response({"result": result})

    async def _handle_print_resume(self, request: web.Request) -> web.Response:
        result = await self._rpc_print_resume({})
        return web.json_response({"result": result})

    async def _handle_print_cancel(self, request: web.Request) -> web.Response:
        result = await self._rpc_print_cancel({})
        return web.json_response({"result": result})

    async def _handle_emergency_stop(self, request: web.Request) -> web.Response:
        result = await self._rpc_emergency_stop({})
        return web.json_response({"result": result})

    async def _handle_firmware_restart(self, request: web.Request) -> web.Response:
        result = await self._rpc_firmware_restart({})
        return web.json_response({"result": result})

    async def _handle_server_info(self, request: web.Request) -> web.Response:
        result = await self._rpc_server_info({})
        return web.json_response({"result": result})

    async def _handle_server_config(self, request: web.Request) -> web.Response:
        result = await self._rpc_server_config({})
        return web.json_response({"result": result})

    async def _handle_temperature_store(self, request: web.Request) -> web.Response:
        result = await self._rpc_temperature_store({})
        return web.json_response({"result": result})

    async def _handle_files_list(self, request: web.Request) -> web.Response:
        root = request.query.get("root", "gcodes")
        result = await self._rpc_files_list({"root": root})
        return web.json_response({"result": result})

    async def _handle_files_directory(self, request: web.Request) -> web.Response:
        path = request.query.get("path", "")
        return web.json_response({
            "dirs": [],
            "files": self._get_kobra_files() if not path else [],
            "disk_usage": 0,
        })

    async def _handle_files_upload(self, request: web.Request) -> web.Response:
        return web.json_response(
            {"error": "File upload not supported on Kobra — use Anycubic slicer or cloud"},
            status=400,
        )

    async def _handle_oneshot_token(self, request: web.Request) -> web.Response:
        return web.json_response({"result": {"token": "kobra-connect-oneshot"}})

    async def _handle_access_info(self, request: web.Request) -> web.Response:
        return web.json_response({
            "result": {
                "default_user": {"username": "kobra", "name": "Kobra"},
                "authentication": {"enabled": False},
            }
        })

    async def _handle_system_info(self, request: web.Request) -> web.Response:
        return web.json_response({
            "result": {
                "system_info": {
                    "cpu_info": {
                        "cpu_count": 4,
                        "bits": "64bit",
                        "processor": "ARM Cortex-A53",
                    },
                    "memory_info": {
                        "total": 1024 * 1024 * 1024,
                        "available": 512 * 1024 * 1024,
                    },
                    "os_info": {
                        "id": "kobra-connect",
                        "version_id": "0.2.0",
                    },
                }
            }
        })

    # -- Webcam Handlers ---------------------------------------------------------

    async def _handle_webcam(self, request: web.Request) -> web.Response:
        """Handle webcam requests - check action query param or path."""
        action = request.query.get("action", "stream")
        if request.path.endswith("/stream"):
            action = "stream"
        elif request.path.endswith("/snapshot"):
            action = "snapshot"

        if action == "snapshot":
            return await self._handle_webcam_snapshot(request)
        else:
            return await self._handle_webcam_stream(request)

    async def _handle_webcam_stream(self, request: web.Request) -> web.Response:
        """Proxy MJPEG stream from Axis camera."""
        stream_url = f"{self.webcam_url}/axis-cgi/mjpg/video.cgi"
        logger.info("Proxying webcam stream from %s", stream_url)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(stream_url) as resp:
                    if resp.status != 200:
                        return web.Response(status=502, text="Failed to fetch stream")

                    # Stream the MJPEG response
                    response = web.StreamResponse(
                        status=resp.status,
                        headers={
                            "Content-Type": "multipart/x-mixed-replace; boundary=myboundary",
                            "Cache-Control": "no-cache",
                        }
                    )
                    await response.prepare(request)

                    async for chunk in resp.content.iter_chunked(8192):
                        await response.write(chunk)

                    return response
        except Exception as e:
            logger.error("Webcam stream error: %s", e)
            return web.Response(status=502, text="Webcam unavailable")

    async def _handle_webcam_snapshot(self, request: web.Request) -> web.Response:
        """Proxy snapshot from Axis camera."""
        snapshot_url = f"{self.webcam_url}/axis-cgi/jpg/image.cgi"
        logger.info("Proxying webcam snapshot from %s", snapshot_url)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(snapshot_url) as resp:
                    if resp.status != 200:
                        return web.Response(status=502, text="Failed to fetch snapshot")

                    content = await resp.read()
                    return web.Response(
                        body=content,
                        content_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"}
                    )
        except Exception as e:
            logger.error("Webcam snapshot error: %s", e)
            return web.Response(status=502, text="Webcam unavailable")

    async def _handle_server_webcams_list(self, request: web.Request) -> web.Response:
        """Moonraker /server/webcams/list endpoint - returns list of configured webcams."""
        return web.json_response({
            "webcams": [
                {
                    "name": "Kobra Webcam",
                    "location": "printer",
                    "service": "mjpegstreamer",
                    "enabled": True,
                    "icon": "mdiWebcam",
                    "target_fps": 20,
                    "target_fps_idle": 5,
                    "stream_url": "/webcam/?action=stream",
                    "snapshot_url": "/webcam/?action=snapshot",
                    "flip_horizontal": False,
                    "flip_vertical": False,
                    "rotation": 0,
                    "aspect_ratio": "4:3",
                    "extra_data": {},
                    "source": "config",
                    "uid": "kobra-webcam-001",
                }
            ]
        })

    async def _handle_server_webcams_item(self, request: web.Request) -> web.Response:
        """Moonraker /server/webcams/item endpoint - returns single webcam by uid or name."""
        uid = request.query.get("uid")
        name = request.query.get("name")

        webcam = {
            "name": "Kobra Webcam",
            "location": "printer",
            "service": "mjpegstreamer",
            "enabled": True,
            "icon": "mdiWebcam",
            "target_fps": 20,
            "target_fps_idle": 5,
            "stream_url": "/webcam/stream",
            "snapshot_url": "/webcam/snapshot",
            "flip_horizontal": False,
            "flip_vertical": False,
            "rotation": 0,
            "aspect_ratio": "4:3",
            "extra_data": {},
            "source": "config",
            "uid": "kobra-webcam-001",
        }

        if uid and uid != webcam["uid"] and name != webcam["name"]:
            return web.json_response({"error": "Webcam not found"}, status=404)

        return web.json_response({"webcam": webcam})

    async def _rpc_server_webcams_list(self, params: dict) -> dict:
        """Handle server.webcams.list via JSON-RPC"""
        return {
            "webcams": [
                {
                    "name": "Kobra Webcam",
                    "location": "printer",
                    "service": "mjpegstreamer",
                    "enabled": True,
                    "icon": "mdiWebcam",
                    "target_fps": 20,
                    "target_fps_idle": 5,
                    "stream_url": "/webcam/?action=stream",
                    "snapshot_url": "/webcam/?action=snapshot",
                    "flip_horizontal": False,
                    "flip_vertical": False,
                    "rotation": 0,
                    "aspect_ratio": "4:3",
                    "extra_data": {},
                    "source": "config",
                    "uid": "kobra-webcam-001",
                }
            ]
        }

    # -- WebSocket Broadcasting ------------------------------------------------

    def _broadcast_status_update(self) -> None:
        """Send notify_status_update to all connected WS clients."""
        if not self._ws_clients or not self._server_loop:
            return

        # Build full status for notify_status_update
        update = {
            "jsonrpc": JSONRPC_VERSION,
            "method": "notify_status_update",
            "params": {
                "status": self._build_full_status(),
                "eventtime": time.time(),
            }
        }
        msg = json.dumps(update)

        with self._ws_lock:
            for ws in list(self._ws_clients):
                if not ws.closed:
                    try:
                        asyncio.run_coroutine_threadsafe(ws.send_str(msg), self._server_loop)
                    except Exception as e:
                        logger.warning("Failed to send WS update: %s", e)

    def _build_full_status(self) -> dict:
        """Build full status for notify_status_update."""
        return {
            "print_stats": self._state.print_stats.to_dict(),
            "virtual_sdcard": self._state.virtual_sdcard.to_dict(),
            "extruder": self._state.extruder.to_dict(),
            "heater_bed": self._state.heater_bed.to_dict(),
            "webhooks": self._state.webhooks.to_dict(),
            "gcode_move": self._state.gcode_move.to_dict(),
            "toolhead": self._state.toolhead.to_dict(),
        }


def run_bridge(host: str, port: int = 7125) -> KobraMoonrakerBridge:
    """Convenience function to create and start bridge."""
    bridge = KobraMoonrakerBridge(host, port)
    bridge.start()
    return bridge