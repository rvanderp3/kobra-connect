"""Main bridge: Kobra MQTT -> Moonraker API emulation."""

from __future__ import annotations

import asyncio
import json
import logging
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
        self._app.router.add_post("/printer/objects/query", self._handle_query)
        self._app.router.add_post("/printer/objects/subscribe", self._handle_subscribe)
        self._app.router.add_get("/printer/objects/list", self._handle_list)
        self._app.router.add_post("/printer/gcode/script", self._handle_gcode_script)
        self._app.router.add_post("/printer/print/start", self._handle_print_start)
        self._app.router.add_post("/printer/print/pause", self._handle_print_pause)
        self._app.router.add_post("/printer/print/resume", self._handle_print_resume)
        self._app.router.add_post("/printer/print/cancel", self._handle_print_cancel)
        self._app.router.add_post("/printer/emergency_stop", self._handle_emergency_stop)
        self._app.router.add_post("/printer/firmware_restart", self._handle_firmware_restart)
        self._app.router.add_get("/server/info", self._handle_server_info)
        self._app.router.add_get("/access/oneshot_token", self._handle_oneshot_token)
        # Webcam endpoints - single handler checks action query param
        self._app.router.add_get("/webcam/", self._handle_webcam)
        self._app.router.add_get("/webcam/stream", self._handle_webcam_stream)
        self._app.router.add_get("/webcam/snapshot", self._handle_webcam_snapshot)
        # Moonraker webcam API for companion discovery
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

        logger.info("WebSocket client connected: %s", request.remote)

        try:
            # Send initial connected notification
            await ws.send_json({
                "jsonrpc": JSONRPC_VERSION,
                "method": "notify_klippy_connected",
                "params": {"state": "ready"}
            })

            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self._handle_ws_message(ws, msg.data)
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error("WS error: %s", ws.exception())
        finally:
            with self._ws_lock:
                self._ws_clients.discard(ws)
            logger.info("WebSocket client disconnected: %s", request.remote)

        return ws

    async def _handle_ws_message(self, ws: web.WebSocketResponse, data: str) -> None:
        """Handle incoming WebSocket JSON-RPC message."""
        try:
            msg = json.loads(data)
            msg_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {})

            logger.debug("WS recv: %s (id=%s)", method, msg_id)

            # Handle as request (expects response)
            if msg_id is not None:
                result = await self._dispatch_jsonrpc(method, params)
                await ws.send_str(JsonRpcResponse(msg_id, result).to_json())
            else:
                # Notification (no response)
                await self._dispatch_jsonrpc(method, params)

        except json.JSONDecodeError:
            logger.warning("Invalid JSON from WS: %s", data)
        except Exception as e:
            logger.error("WS message handler error: %s", e, exc_info=True)
            if msg_id is not None:
                await ws.send_str(JsonRpcResponse(msg_id, error={"code": -32603, "message": str(e)}).to_json())

    async def _dispatch_jsonrpc(self, method: str, params: dict) -> Any:
        """Dispatch JSON-RPC method to handler."""
        handlers = {
            "printer.objects.query": self._rpc_query,
            "printer.objects.subscribe": self._rpc_subscribe,
            "printer.objects.list": self._rpc_list,
            "printer.gcode.script": self._rpc_gcode_script,
            "printer.print.start": self._rpc_print_start,
            "printer.print.pause": self._rpc_print_pause,
            "printer.print.resume": self._rpc_print_resume,
            "printer.print.cancel": self._rpc_print_cancel,
            "printer.emergency_stop": self._rpc_emergency_stop,
            "printer.firmware_restart": self._rpc_firmware_restart,
            "server.info": self._rpc_server_info,
            "server.webcams.list": self._rpc_server_webcams_list,
        }

        handler = handlers.get(method)
        if not handler:
            return {"error": {"code": -32601, "message": f"Method not found: {method}"}}

        try:
            return await handler(params)
        except Exception as e:
            logger.error("RPC %s failed: %s", method, e, exc_info=True)
            return {"error": {"code": -32603, "message": str(e)}}

    # -- JSON-RPC Handlers -----------------------------------------------------

    async def _rpc_query(self, params: dict) -> dict:
        """Handle printer.objects.query"""
        objects = params.get("objects", {})
        result = self._state.to_query_result(objects)
        result["eventtime"] = time.time()
        return result

    async def _rpc_subscribe(self, params: dict) -> dict:
        """Handle printer.objects.subscribe"""
        objects = params.get("objects", {})
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

    async def _rpc_gcode_script(self, params: dict) -> str:
        """Handle printer.gcode.script - forward to Kobra if connected"""
        script = params.get("script", "")
        logger.info("G-code script requested: %s", script[:100])
        # TODO: Implement actual G-code sending via Kobra MQTT
        return "ok"

    async def _rpc_print_start(self, params: dict) -> str:
        """Handle printer.print.start"""
        filename = params.get("filename", "")
        logger.info("Print start requested: %s", filename)
        # TODO: Implement via Kobra MQTT
        return "ok"

    async def _rpc_print_pause(self, params: dict) -> str:
        """Handle printer.print.pause"""
        logger.info("Print pause requested")
        # TODO: Implement via Kobra MQTT
        return "ok"

    async def _rpc_print_resume(self, params: dict) -> str:
        """Handle printer.print.resume"""
        logger.info("Print resume requested")
        # TODO: Implement via Kobra MQTT
        return "ok"

    async def _rpc_print_cancel(self, params: dict) -> str:
        """Handle printer.print.cancel"""
        logger.info("Print cancel requested")
        # TODO: Implement via Kobra MQTT
        return "ok"

    async def _rpc_emergency_stop(self, params: dict) -> str:
        """Handle printer.emergency_stop"""
        logger.warning("Emergency stop requested!")
        # TODO: Implement via Kobra MQTT
        return "ok"

    async def _rpc_firmware_restart(self, params: dict) -> str:
        """Handle printer.firmware_restart"""
        logger.warning("Firmware restart requested!")
        return "ok"

    async def _rpc_server_info(self, params: dict) -> dict:
        """Handle server.info"""
        return {
            "klippy_state": "ready",
            "klippy_connected": True,
            "hostname": "kobra-connect",
            "software_version": "kobra-connect-0.1.0",
            "api_version": "1.0",
        }

    async def _rpc_server_webcams_list(self, params: dict) -> dict:
        """Handle server.webcams.list via JSON-RPC"""
        return await self._handle_server_webcams_list_jsonrpc(params)

    async def _handle_server_webcams_list_jsonrpc(self, params: dict) -> dict:
        """Return webcams list for JSON-RPC"""
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

    async def _handle_gcode_script(self, request: web.Request) -> web.Response:
        params = await request.json()
        result = await self._rpc_gcode_script(params)
        return web.json_response({"result": result})

    async def _handle_print_start(self, request: web.Request) -> web.Response:
        params = await request.json()
        result = await self._rpc_print_start(params)
        return web.json_response({"result": result})

    async def _handle_print_pause(self, request: web.Request) -> web.Response:
        params = await request.json()
        result = await self._rpc_print_pause(params)
        return web.json_response({"result": result})

    async def _handle_print_resume(self, request: web.Request) -> web.Response:
        params = await request.json()
        result = await self._rpc_print_resume(params)
        return web.json_response({"result": result})

    async def _handle_print_cancel(self, request: web.Request) -> web.Response:
        params = await request.json()
        result = await self._rpc_print_cancel(params)
        return web.json_response({"result": result})

    async def _handle_emergency_stop(self, request: web.Request) -> web.Response:
        params = await request.json()
        result = await self._rpc_emergency_stop(params)
        return web.json_response({"result": result})

    async def _handle_firmware_restart(self, request: web.Request) -> web.Response:
        params = await request.json()
        result = await self._rpc_firmware_restart(params)
        return web.json_response({"result": result})

    async def _handle_server_info(self, request: web.Request) -> web.Response:
        result = await self._rpc_server_info({})
        return web.json_response({"result": result})

    async def _handle_oneshot_token(self, request: web.Request) -> web.Response:
        # Return a dummy token for compatibility
        return web.json_response({"result": {"token": "kobra-connect-oneshot"}})

    # -- Webcam Handlers ---------------------------------------------------------

    async def _handle_webcam(self, request: web.Request) -> web.Response:
        """Handle webcam requests - check action query param or path."""
        action = request.query.get("action", "stream")
        # Also check path for Moonraker-style /webcam/stream and /webcam/snapshot
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