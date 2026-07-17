"""LAN-Mode handshake: GET /info → signed POST /ctrl → AES-CBC decrypt → MQTT credentials."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import re
import string
import time
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from .models import HandshakeResult


class HandshakeError(Exception):
    """Raised when the LAN handshake fails."""


class CloudModeError(HandshakeError):
    """Raised when the printer is in cloud mode instead of LAN mode."""


def _http_fetch(method: str, url: str) -> dict[str, Any]:
    logger.info("HTTP %s %s", method, url.split("?")[0])
    req = urllib.request.Request(url, method=method)
    if method == "POST":
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read()
        logger.info("HTTP %s %s → %d (%d bytes)", method, url.split("?")[0], resp.status, len(body))
        return json.loads(body)


def _sign(token: str, ts: int, nonce: str) -> str:
    """sign = md5(md5(token[:16]) + str(ts) + nonce)."""
    first = hashlib.md5(token[:16].encode()).hexdigest()
    return hashlib.md5((first + str(ts) + nonce).encode()).hexdigest()


def _decrypt_ctrl(info_b64: str, token: str, local_token: str) -> dict:
    """AES-CBC decrypt the /ctrl data.info blob. key=token[16:32], IV=local_token (pad/trunc 16)."""
    key = token[16:32].encode()
    iv = local_token.encode()[:16].ljust(16, b"\0")
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = dec.update(base64.b64decode(info_b64)) + dec.finalize()
    unpadder = PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    return json.loads(plaintext.decode())


def _parse_mac(usn: str | None) -> str | None:
    if not usn:
        return None
    m = re.search(r"([0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){5})", usn)
    return m.group(1) if m else None


def do_handshake(host: str) -> HandshakeResult:
    """Run the full LAN handshake: GET /info → signed POST /ctrl → AES decrypt.

    Returns a HandshakeResult with MQTT broker credentials.
    Raises CloudModeError if the printer is in cloud mode.
    Raises HandshakeError for other failures.
    """
    info = _http_fetch("GET", f"http://{host}:18910/info")

    if info.get("ctrlType") == "cloud":
        raise CloudModeError("Printer is in CLOUD mode — enable LAN Mode on the printer")

    token = info.get("token")
    ctrl_url = info.get("ctrlInfoUrl")
    model_id = info.get("modelId")

    if not token or not ctrl_url or not model_id:
        raise HandshakeError(
            "This printer doesn't use the signed LAN handshake "
            "(Kobra 3 / S1 generation required)"
        )

    ts = int(time.time() * 1000)
    nonce = "".join(random.choices(string.ascii_letters + string.digits, k=6))
    did = "".join(random.choices(string.ascii_uppercase + string.digits, k=32))

    qs = urllib.parse.urlencode({
        "ts": ts,
        "nonce": nonce,
        "sign": _sign(token, ts, nonce),
        "did": did,
    })

    ctrl = _http_fetch("POST", f"{ctrl_url}?{qs}")
    if ctrl.get("code") != 200:
        raise HandshakeError(f"/ctrl failed: {ctrl.get('message')}")

    data = _decrypt_ctrl(ctrl["data"]["info"], token, ctrl["data"]["token"])

    m = re.match(r"mqtts?://([^:]+):(\d+)", data["broker"])
    if not m:
        raise HandshakeError(f"Cannot parse broker URL: {data['broker']}")

    return HandshakeResult(
        broker_host=m.group(1),
        broker_port=int(m.group(2)),
        username=data["username"],
        password=data["password"],
        device_id=data["deviceId"],
        model_id=str(model_id),
        serial=info.get("cn", ""),
        device_cert=data.get("devicecrt", ""),
        device_key=data.get("devicepk", ""),
        mac=_parse_mac(info.get("usn")),
        model_name=info.get("modelName"),
        device_type=info.get("deviceType"),
    )
