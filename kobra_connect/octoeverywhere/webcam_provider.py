"""Camera snapshot provider supporting RTSP and internal Kobra webcam."""

from __future__ import annotations

import logging
import subprocess
import tempfile
import os
from typing import Optional

logger = logging.getLogger(__name__)

_RTSP_URL = "rtsp://root:cat80%3BCAT@192.168.0.35/axis-media/media.amp?videocodec=jpeg&resolution=640x480&fps=10"

_INTERNAL_CAM_URL = "http://192.168.0.71:18910/camera/snapshot"

_PLACEHOLDER: Optional[bytes] = None


def _get_placeholder() -> bytes:
    global _PLACEHOLDER
    if _PLACEHOLDER is None:
        from .status_pusher import _PLACEHOLDER_IMAGE
        _PLACEHOLDER = _PLACEHOLDER_IMAGE
    return _PLACEHOLDER


def _capture_rtsp() -> Optional[bytes]:
    """Capture a single JPEG frame from the RTSP camera via ffmpeg."""
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    try:
        cmd = [
            "ffmpeg", "-y",
            "-rtsp_transport", "tcp",
            "-i", _RTSP_URL,
            "-vframes", "1",
            "-f", "image2",
            tmp.name,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode != 0:
            logger.debug("RTSP capture failed: %s", result.stderr[:200].decode(errors="replace"))
            return None
        with open(tmp.name, "rb") as f:
            data = f.read()
        if len(data) > 100:
            return data
        return None
    except Exception as e:
        logger.debug("RTSP capture error: %s", e)
        return None
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def _capture_internal() -> Optional[bytes]:
    """Capture a snapshot from the Kobra 3's built-in camera."""
    try:
        import urllib.request
        req = urllib.request.Request(_INTERNAL_CAM_URL, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
            if len(data) > 100:
                return data
        return None
    except Exception as e:
        logger.debug("Internal cam capture error: %s", e)
        return None


def capture_snapshot() -> bytes:
    """Capture a JPEG snapshot. Tries RTSP first, then internal camera, then placeholder."""
    img = _capture_rtsp()
    if img:
        logger.info("Camera: RTSP snapshot (%d bytes)", len(img))
        return img
    img = _capture_internal()
    if img:
        logger.info("Camera: internal snapshot (%d bytes)", len(img))
        return img
    logger.info("Camera: using placeholder snapshot")
    return _get_placeholder()
