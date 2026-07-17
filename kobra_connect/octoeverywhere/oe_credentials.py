"""OctoEverywhere credential generation and storage.

Manages printerId + privateKey for OE cloud authentication.
Credentials are stored in an INI file at ``<data_dir>/octoeverywhere.secrets``.
"""

from __future__ import annotations

import configparser
import logging
import os
import secrets
import string
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_SECRETS_FILE = "octoeverywhere.secrets"


@dataclass
class OeCredentials:
    printer_id: str
    private_key: str
    octokey: str = ""


def _generate_printer_id() -> str:
    """60 chars: uppercase ASCII + digits (matches OE convention)."""
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(60))


def _generate_private_key() -> str:
    """80 chars: mixed-case ASCII + digits (matches OE convention)."""
    chars = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(80))


def _secrets_path(data_dir: str) -> Path:
    return Path(data_dir) / _SECRETS_FILE


def load_or_create(data_dir: str) -> OeCredentials:
    """Load existing credentials or generate new ones.

    Returns the credentials and a flag indicating if they are new.
    """
    path = _secrets_path(data_dir)
    if path.exists():
        cfg = configparser.ConfigParser()
        cfg.read(path)
        try:
            pid = cfg.get("secrets", "printer_id")
            pkey = cfg.get("secrets", "private_key")
            ok = cfg.get("secrets", "octokey", fallback="")
            logger.info("Loaded existing OE credentials from %s", path)
            return OeCredentials(printer_id=pid, private_key=pkey, octokey=ok)
        except (configparser.NoSectionError, configparser.NoOptionError):
            logger.warning("Corrupt secrets file, regenerating")

    creds = OeCredentials(
        printer_id=_generate_printer_id(),
        private_key=_generate_private_key(),
    )
    save(creds, data_dir)
    logger.info("Generated new OE credentials → %s", path)
    return creds


def save(creds: OeCredentials, data_dir: str) -> None:
    """Write credentials to the secrets file."""
    path = _secrets_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = configparser.ConfigParser()
    cfg["secrets"] = {
        "printer_id": creds.printer_id,
        "private_key": creds.private_key,
    }
    if creds.octokey:
        cfg["secrets"]["octokey"] = creds.octokey
    with open(path, "w") as f:
        cfg.write(f)
    # Restrict permissions on Unix
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
