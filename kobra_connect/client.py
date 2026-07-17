"""MQTT client for communicating with a Kobra 3 printer over LAN."""

from __future__ import annotations

import json
import ssl
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import paho.mqtt.client as mqtt

from .handshake import HandshakeError, do_handshake
from .models import FanSpeed, HandshakeResult, PrinterInfo, Temperature

_PREFIX = "anycubic/anycubicCloud/v1"

OnReport = Callable[[str, dict], None]


class KobraClient:
    """Synchronous client for a Kobra 3 / S1 printer on the local network.

    Usage::

        client = KobraClient("192.168.0.71")
        client.connect()           # handshake + MQTT connect
        temps = client.query_temperature()
        print(temps.curr_nozzle)   # e.g. 225.0

        # or stay subscribed for live updates:
        client.on_report = lambda topic, data: print(data)
        client.subscribe_all()
        client.loop_forever()
    """

    def __init__(self, host: str) -> None:
        self.host = host
        self._hs: HandshakeResult | None = None
        self._client: mqtt.Client | None = None
        self._cert_path: str | None = None
        self._key_path: str | None = None
        self.on_report: OnReport | None = None
        self._last_reports: dict[str, dict] = {}
        self._connected_event = threading.Event()

    # -- connection ----------------------------------------------------------

    def handshake(self) -> HandshakeResult:
        """Run the LAN handshake to discover MQTT credentials."""
        self._hs = do_handshake(self.host)
        return self._hs

    def connect(self, timeout: float = 10.0) -> HandshakeResult:
        """Handshake + MQTT connect. Blocks until MQTT connection is established."""
        if not self._hs:
            self.handshake()
        assert self._hs is not None

        self._cert_path = tempfile.mktemp(suffix=".pem")
        self._key_path = tempfile.mktemp(suffix=".pem")
        Path(self._cert_path).write_text(self._hs.device_cert)
        Path(self._key_path).write_text(self._hs.device_key)

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"kobra-{uuid.uuid4().hex[:8]}",
        )
        self._client.username_pw_set(self._hs.username, self._hs.password)
        self._client.tls_set(
            self._cert_path,
            keyfile=self._key_path,
            cert_reqs=ssl.CERT_NONE,
        )
        self._client.tls_insecure_set(True)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        self._connected_event.clear()
        self._client.connect(self._hs.broker_host, self._hs.broker_port, keepalive=60)
        self._client.loop_start()

        if not self._connected_event.wait(timeout):
            self.disconnect()
            raise HandshakeError(f"MQTT connect timed out after {timeout}s")

        return self._hs

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker and clean up."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
        for p in (self._cert_path, self._key_path):
            if p:
                try:
                    Path(p).unlink()
                except OSError:
                    pass
        self._cert_path = self._key_path = None

    # -- queries (blocking) --------------------------------------------------

    def query(self, msg_type: str, timeout: float = 5.0) -> dict:
        """Send a single query and wait for the report. Returns the report data dict."""
        if not self._client or not self._hs:
            raise HandshakeError("Not connected — call connect() first")

        topic = f"{_PREFIX}/web/printer/{self._hs.model_id}/{self._hs.device_id}/{msg_type}"
        body = json.dumps({
            "type": msg_type,
            "action": "query",
            "timestamp": int(time.time() * 1000),
            "msgid": uuid.uuid4().hex,
            "data": None,
        })

        report_topic = f"{_PREFIX}/printer/public/{self._hs.model_id}/{self._hs.device_id}/{msg_type}/report"
        result: dict = {}
        event = threading.Event()

        def handler(_client: mqtt.Client, _ud: object, msg: mqtt.MQTTMessage) -> None:
            if msg.topic == report_topic:
                result.update(json.loads(msg.payload))
                event.set()

        old_handler = self._client.on_message
        self._client.on_message = handler
        self._client.publish(topic, body)
        event.wait(timeout)
        self._client.on_message = old_handler

        return result

    def query_temperature(self) -> Temperature:
        """Query current nozzle and bed temperatures."""
        report = self.query("tempature")
        return Temperature.from_dict(report.get("data", {}))

    def query_info(self) -> PrinterInfo:
        """Query full printer info (temps, state, progress, etc.)."""
        report = self.query("info")
        return PrinterInfo.from_dict(report.get("data", {}))

    def query_fan_speed(self) -> FanSpeed:
        """Query fan speeds."""
        report = self.query("fan")
        return FanSpeed.from_dict(report.get("data", {}))

    # -- subscriptions (async via loop) --------------------------------------

    def subscribe_all(self) -> None:
        """Subscribe to all printer report topics."""
        if not self._client or not self._hs:
            raise HandshakeError("Not connected — call connect() first")
        topic = f"{_PREFIX}/printer/public/{self._hs.model_id}/{self._hs.device_id}/#"
        self._client.subscribe(topic)

    def loop_forever(self) -> None:
        """Block and process MQTT messages forever."""
        if self._client:
            self._client.loop_forever()

    # -- internals -----------------------------------------------------------

    def _on_connect(self, client: mqtt.Client, _ud: object, _flags: object, rc: int, _props: object) -> None:
        if rc == 0:
            self.subscribe_all()
            self._connected_event.set()

    def _on_message(self, _client: mqtt.Client, _ud: object, msg: mqtt.MQTTMessage) -> None:
        try:
            data = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        self._last_reports[msg.topic] = data
        if self.on_report:
            self.on_report(msg.topic, data)

    def __enter__(self) -> KobraClient:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()
