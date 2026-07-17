"""OctoEverywhere cloud WebSocket client.

Handles the full OE companion protocol:
- WebSocket connection to the OE cloud
- RSA challenge-response authentication
- WebStreamMsg dispatching to the command router
- Reconnection with exponential backoff
"""

from __future__ import annotations

import logging
import os
import random
import string
import threading
import time
from typing import Optional

import websocket
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from .command_router import CommandRouter
from .oe_credentials import OeCredentials, save as save_credentials
from .oe_protocol import (
    DataCompression,
    MessageContext,
    ServerHost,
    WebStreamMsg,
    build_handshake_syn,
    build_webstream_response,
    parse_handshake_ack,
    parse_webstream_msg,
    strip_size_prefix,
    _find_root,
    _vtable_offset,
)

logger = logging.getLogger(__name__)

_OE_WS_URI = "wss://starport-v1.octoeverywhere.com/octoclientwsv2"

_OE_RSA_PUBLIC_KEY_PEM = b"""-----BEGIN RSA PUBLIC KEY-----
MIICCgKCAgEAwOjuEvc4bnY+MNkzG8ztlUhjPcRVSKGX53fuzmjshuwrhNu9KdNO
lvEH4ORZI6S3xnXRhzupWYD8M2CVzsNSKJulNPe5hgoxct2bynoEwzzEKXkuypuw
Vtr+/nETdD+quWdS4oEMvmLFI1+7+Qlq4lqddPgIjC5xAvwN3d1NYJMFY3M7jHaq
2JNK3g6YsEyUYlBFkvrgB8SXjQCrevriANP2UPzZl2uEJh/ibH85CAnfoPPCdGpp
kfY2KG/fzDVv7nE/7SYW/44RUv4BC6wyJY7PB+ZhTXAcVs67hq6l2/dHOUEek455
4vJf08sp85JhmeZgEg9COF5j7rAHnnOjENYVVW9FCQam6vscXETrVYX++6QMD/1G
PdFnZs4KoG2i0LqqC3RoS/Nt3d2CeIl6U+BCueY5icxy5EgsAF4H48yIN7jx1oUd
Jk2TJQsvTnMt7sdIL96v1U/fl7U7kcHxHKXn79Mhtf4yUKnApwEL8JRVmRSL8y8x
MEqQzTZsBYradQXjPL5QSNwgAGhVEYWgmUGmY8esUVF35/HuzgkJmZjgldU5WJGr
6pvONbuDIoAwz2EnyVS7r+IL6Eqy2xbA8h5YllJ/qcau5V4YGt2C4JDK4PuX4gTM
71iVsKozshWsXK8ctySQ0Jbc0O0zVlRTzCw0xH78lWaSHU7H2GitYF0CAwEAAQ==
-----END RSA PUBLIC KEY-----"""

_RNG = string.ascii_letters + string.digits


class OeClient:
    """Standalone OctoEverywhere cloud client for Kobra 3 companions.

    Usage::

        router = CommandRouter()
        creds = load_or_create(data_dir)
        client = OeClient(creds, router)
        client.run()  # blocks, reconnects on failure
    """

    def __init__(
        self,
        credentials: OeCredentials,
        router: CommandRouter,
        server_host: int = ServerHost.Moonraker,
        local_ip: str = "",
        data_dir: str = "",
    ) -> None:
        self._creds = credentials
        self._router = router
        self._server_host = server_host
        self._local_ip = local_ip
        self._data_dir = data_dir

        self._ws: Optional[websocket.WebSocketApp] = None
        self._challenge: str = ""
        self._connected = threading.Event()
        self._stop = threading.Event()
        self._octokey: str = ""

    @property
    def octokey(self) -> str:
        """The octokey returned by the OE cloud during handshake."""
        return self._octokey

    # -- public API ----------------------------------------------------------

    def run(self) -> None:
        """Connect to OE cloud and block. Reconnects on failure."""
        self._stop.clear()
        backoff = 1.0

        while not self._stop.is_set():
            try:
                self._connect_and_run()
            except Exception:
                if self._stop.is_set():
                    break
                wait = min(backoff + random.uniform(10, 30), 180)
                logger.warning("Disconnected. Reconnecting in %.0fs ...", wait)
                time.sleep(wait)
                backoff = min(backoff * 2, 180)
            else:
                backoff = 1.0

    def stop(self) -> None:
        """Signal the client to stop."""
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    # -- internal ------------------------------------------------------------

    def _connect_and_run(self) -> None:
        logger.info("Connecting to OE cloud at %s ...", _OE_WS_URI)

        self._ws = websocket.WebSocketApp(
            _OE_WS_URI,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        self._ws.run_forever(
            ping_interval=30,
            ping_timeout=20,
            sslopt={"cert_reqs": 0},  # CERT_NONE — OE uses their own CA
            skip_utf8_validation=True,
        )

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        logger.info("WebSocket connected. Starting handshake ...")
        self._send_handshake_syn()

    def _on_message(self, ws: websocket.WebSocketApp, message: str | bytes) -> None:
        if isinstance(message, str):
            message = message.encode("utf-8")

        try:
            self._handle_message(message)
        except Exception:
            logger.exception("Error handling OE message")

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        logger.error("WebSocket error: %s: %s", type(error).__name__, error)

    def _on_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        logger.info("WebSocket closed (code=%s, msg=%s)", close_status_code, close_msg)
        self._connected.clear()

    # -- handshake -----------------------------------------------------------

    def _send_handshake_syn(self) -> None:
        self._challenge = "".join(random.choices(_RNG, k=64))
        rsa_pub = load_pem_public_key(_OE_RSA_PUBLIC_KEY_PEM)
        encrypted = rsa_pub.encrypt(
            self._challenge.encode("utf-8"),
            padding.PKCS1v15(),
        )

        msg = build_handshake_syn(
            printer_id=self._creds.printer_id,
            private_key=self._creds.private_key,
            rsa_challenge=encrypted,
            plugin_version="kobra-connect-0.1.0",
            local_device_ip=self._local_ip,
            server_host=self._server_host,
            octokey=self._creds.octokey,
            webcam_url="http://localhost/webcam/?action=snapshot",
        )
        self._send(msg)

    def _handle_handshake_ack(self, data: bytes) -> None:
        ack = parse_handshake_ack(data)
        if not ack.accepted:
            logger.error(
                "Handshake rejected: %s (rekey=%s, update=%s)",
                ack.error, ack.requires_rekey, ack.requires_plugin_update,
            )
            self.stop()
            return

        # Validate RSA challenge response
        if ack.rsa_challenge_result != self._challenge:
            logger.error("RSA challenge mismatch — server authentication failed")
            self.stop()
            return

        logger.info(
            "Handshake accepted! octokey=%s... accounts=%s",
            ack.octokey[:12] if ack.octokey else "none",
            ack.connected_accounts,
        )
        self._octokey = ack.octokey
        # Persist the OctoKey for reconnection
        if ack.octokey and self._data_dir:
            self._creds.octokey = ack.octokey
            try:
                save_credentials(self._creds, self._data_dir)
            except Exception:
                logger.exception("Failed to persist OctoKey")
        self._connected.set()

    # -- WebStreamMsg handling -----------------------------------------------

    def _handle_webstream_msg(self, data: bytes) -> None:
        msg = parse_webstream_msg(data)
        if msg is None:
            logger.warning("Failed to parse WebStreamMsg")
            return

        if msg.is_close_msg:
            logger.debug("Stream %d closed", msg.stream_id)
            return

        if not msg.is_open_msg and not msg.http_path:
            # Data message on existing stream — not expected for monitoring MVP
            return

        # New stream with HTTP context
        path = msg.http_path
        method = msg.http_method
        body = msg.data if msg.data else None

        if msg.http_use_auth:
            logger.info("HTTP %s %s (stream %d, use_auth=True)", method, path, msg.stream_id)

        status_code, resp_body, content_type = self._router.route(path, body)
        logger.info("HTTP %s %s → %d (%d bytes, stream %d)", method, path, status_code, len(resp_body), msg.stream_id)

        resp_msg = build_webstream_response(
            stream_id=msg.stream_id,
            status_code=status_code,
            body=resp_body,
            content_type=content_type,
        )
        self._send(resp_msg)

    # -- wire ----------------------------------------------------------------

    def _handle_message(self, raw: bytes) -> None:
        logger.debug("Raw message: %d bytes, first 32: %s", len(raw), raw[:32].hex())
        # Strip the 4-byte size prefix
        payload = strip_size_prefix(raw)
        if not payload or len(payload) < 8:
            logger.warning("Message too short after stripping prefix (%d bytes)", len(payload))
            return

        buf = bytearray(payload)
        root = _find_root(buf)
        if root is None:
            logger.warning("Invalid FlatBuffer root in message (%d bytes)", len(payload))
            return

        # Read context_type from slot 0 of the root table
        voff = _vtable_offset(buf, root, 0)
        ctx_type = buf[voff] if voff else 0

        logger.debug("ctx_type=%d root=%d payload_len=%d", ctx_type, root, len(payload))

        if ctx_type == MessageContext.HandshakeAck:
            self._handle_handshake_ack(payload)
        elif ctx_type == MessageContext.WebStreamMsg:
            self._handle_webstream_msg(payload)
        elif ctx_type == MessageContext.OctoNotification:
            logger.info("OE notification received (ignored in MVP)")
        elif ctx_type == MessageContext.OctoSummon:
            logger.info("OE summon request received (ignored in MVP)")
        else:
            logger.debug("Unknown message context type: %d", ctx_type)

    def _send(self, data: bytes) -> None:
        if self._ws and self._ws.sock:
            try:
                self._ws.sock.send_binary(data)
            except Exception:
                logger.exception("Failed to send OE message")
