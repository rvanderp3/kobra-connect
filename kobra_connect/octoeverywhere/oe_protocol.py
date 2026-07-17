"""OctoEverywhere wire protocol — FlatBuffer message builders and parsers.

Implements the minimal subset of the OE protocol needed for a companion:
- HandshakeSyn (client → server)
- HandshakeAck (server → client)
- WebStreamMsg (bidirectional, carries HTTP requests/responses)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import flatbuffers
from flatbuffers import table as fb_table

# ---------------------------------------------------------------------------
# Enum values
# ---------------------------------------------------------------------------

class MessageContext:
    NONE = 0
    HandshakeSyn = 1
    HandshakeAck = 2
    WebStreamMsg = 3
    OctoNotification = 4
    OctoSummon = 5


class ServerHost:
    Unknown = 0
    OctoPrint = 1
    Moonraker = 2
    Bambu = 3
    Elegoo = 4
    Elegoo2 = 5
    PrusaLink = 6


class OsType:
    Unknown = 0


class DataCompression:
    None_ = 0
    Brotli = 1
    Zlib = 2
    ZStandard = 3


class SummonMethod:
    Unknown = 1
    FastPath = 2
    Broadcast = 3


class PathType:
    None_ = 0
    Relative = 1
    Absolute = 2


class OeAuth:
    Deny = 0
    Allow = 1


# ---------------------------------------------------------------------------
# FlatBuffer helpers
# ---------------------------------------------------------------------------

def _create_string(builder: flatbuffers.Builder, s: str) -> int:
    return builder.CreateString(s)


def _create_byte_vector(builder: flatbuffers.Builder, data: bytes) -> int:
    builder.StartVector(1, len(data), 1)
    # Prepend bytes in reverse order (FlatBuffers builds backwards)
    for b in reversed(data):
        builder.PrependByte(b)
    return builder.EndVector()


def _create_string_vector(builder: flatbuffers.Builder, strings: List[str]) -> int:
    offsets = [_create_string(builder, s) for s in strings]
    builder.StartVector(4, len(offsets), 4)
    for o in reversed(offsets):
        builder.PrependUOffsetTRelative(o)
    return builder.EndVector()


def _create_http_headers(builder: flatbuffers.Builder, headers: Dict[str, str]) -> int:
    """Build a vector of HttpHeader tables."""
    offsets = []
    for key, value in headers.items():
        key_off = _create_string(builder, key)
        val_off = _create_string(builder, value)
        builder.StartObject(2)
        builder.PrependUOffsetTRelativeSlot(0, key_off, 0)
        builder.PrependUOffsetTRelativeSlot(1, val_off, 0)
        offsets.append(builder.EndObject())
    builder.StartVector(4, len(offsets), 4)
    for o in reversed(offsets):
        builder.PrependUOffsetTRelative(o)
    return builder.EndVector()


# ---------------------------------------------------------------------------
# HandshakeSyn builder
# ---------------------------------------------------------------------------

def _create_kvp(builder: flatbuffers.Builder, key: str, value: str) -> int:
    """Build a Kvp (key-value pair) table for the handshake properties vector."""
    key_off = builder.CreateString(key)
    val_off = builder.CreateString(value)
    builder.StartObject(2)
    builder.PrependUOffsetTRelativeSlot(0, key_off, 0)  # Key
    builder.PrependUOffsetTRelativeSlot(1, val_off, 0)  # Value
    return builder.EndObject()


def build_handshake_syn(
    printer_id: str,
    private_key: str,
    rsa_challenge: bytes,
    plugin_version: str = "kobra-connect-0.1.0",
    local_device_ip: str = "",
    server_host: int = ServerHost.Moonraker,
    octokey: str = "",
    webcam_url: str = "",
) -> bytes:
    """Build a HandshakeSyn FlatBuffer wrapped in OctoStreamMessage."""
    builder = flatbuffers.Builder(512)

    # Create strings (must be done before starting any table)
    printer_id_off = _create_string(builder, printer_id)
    private_key_off = _create_string(builder, private_key)
    rsa_challenge_off = _create_byte_vector(builder, rsa_challenge)
    plugin_version_off = _create_string(builder, plugin_version)
    local_ip_off = _create_string(builder, local_device_ip) if local_device_ip else 0
    device_id_off = 0  # optional
    octokey_off = _create_string(builder, octokey) if octokey else 0

    # Build properties vector with webcam URL
    properties = []
    if webcam_url:
        properties.append(_create_kvp(builder, "WebcamUrl", webcam_url))
    properties_off = 0
    if properties:
        builder.StartVector(4, len(properties), 4)
        for off in reversed(properties):
            builder.PrependUOffsetTRelative(off)
        properties_off = builder.EndVector()

    # Build HandshakeSyn table (20 fields)
    builder.StartObject(20)
    builder.PrependUOffsetTRelativeSlot(0, printer_id_off, 0)       # printer_id
    builder.PrependBoolSlot(1, True, False)                          # is_primary_connection
    builder.PrependUOffsetTRelativeSlot(2, plugin_version_off, 0)   # plugin_version
    builder.PrependUOffsetTRelativeSlot(3, local_ip_off, 0)         # local_device_ip
    builder.PrependUint32Slot(4, 0, 0)                              # local_http_proxy_port
    builder.PrependUOffsetTRelativeSlot(5, octokey_off, 0)          # key (persistent OctoKey)
    builder.PrependUOffsetTRelativeSlot(6, rsa_challenge_off, 0)    # rsa_challenge
    builder.PrependInt8Slot(7, 1, 0)                                # ras_challenge_version
    builder.PrependBoolSlot(8, False, False)                         # webcam_flip_h
    builder.PrependBoolSlot(9, False, False)                         # webcam_flip_v
    builder.PrependBoolSlot(10, False, False)                        # webcam_flip_rotate90
    builder.PrependUOffsetTRelativeSlot(11, private_key_off, 0)     # private_key
    builder.PrependInt8Slot(12, SummonMethod.Unknown, 0)            # summon_method
    builder.PrependInt8Slot(13, server_host, 0)                     # server_host
    builder.PrependBoolSlot(14, False, False)                        # is_companion
    builder.PrependInt8Slot(15, OsType.Unknown, 0)                  # os_type
    builder.PrependInt8Slot(16, DataCompression.Zlib, 0)            # receive_compression_type
    builder.PrependUOffsetTRelativeSlot(17, device_id_off, 0)       # device_id
    builder.PrependBoolSlot(18, False, False)                        # is_docker_container
    builder.PrependUOffsetTRelativeSlot(19, properties_off, 0)      # properties
    handshake_syn_off = builder.EndObject()

    # Build OctoStreamMessage wrapping HandshakeSyn
    builder.StartObject(2)
    builder.PrependUint8Slot(0, MessageContext.HandshakeSyn, 0)
    builder.PrependUOffsetTRelativeSlot(1, handshake_syn_off, 0)
    root = builder.EndObject()

    builder.FinishSizePrefixed(root)
    return bytes(builder.Output())


# ---------------------------------------------------------------------------
# HandshakeAck parser
# ---------------------------------------------------------------------------

@dataclass
class HandshakeAck:
    accepted: bool = False
    connected_accounts: List[str] = field(default_factory=list)
    error: str = ""
    backoff_seconds: int = 0
    requires_plugin_update: bool = False
    octokey: str = ""
    rsa_challenge_result: str = ""
    requires_rekey: bool = False


def parse_handshake_ack(data: bytes) -> HandshakeAck:
    """Parse a HandshakeAck from the raw FlatBuffer bytes (after size prefix)."""
    buf = bytearray(data)
    # Find the HandshakeAck table inside OctoStreamMessage
    root = _find_root(buf)
    if root is None:
        return HandshakeAck(error="Failed to parse: no valid root table")

    inner = _find_inner_table(buf, root, MessageContext.HandshakeAck)
    if inner is None:
        return HandshakeAck(error="Failed to parse HandshakeAck")

    accepted = _read_bool_field(buf, inner, 0)
    connected_accounts = _read_string_vector(buf, inner, 1)
    error = _read_string_field(buf, inner, 2)
    backoff_seconds = _read_uint64_field(buf, inner, 3)
    requires_plugin_update = _read_bool_field(buf, inner, 4)
    octokey = _read_string_field(buf, inner, 5)
    rsa_challenge_result = _read_string_field(buf, inner, 6)
    requires_rekey = _read_bool_field(buf, inner, 7)

    return HandshakeAck(
        accepted=accepted,
        connected_accounts=connected_accounts,
        error=error,
        backoff_seconds=backoff_seconds,
        requires_plugin_update=requires_plugin_update,
        octokey=octokey,
        rsa_challenge_result=rsa_challenge_result,
        requires_rekey=requires_rekey,
    )


# ---------------------------------------------------------------------------
# WebStreamMsg parser
# ---------------------------------------------------------------------------

@dataclass
class WebStreamMsg:
    stream_id: int = 0
    is_open_msg: bool = False
    is_close_msg: bool = False
    is_data_transmission_done: bool = False
    is_control_flags_only: bool = True
    full_stream_data_size: int = -1
    data: bytes = b""
    data_compression: int = DataCompression.None_
    original_data_size: int = 0
    status_code: int = 0
    # HTTP context (only on open messages from server)
    http_path: str = ""
    http_method: str = ""
    http_headers: Dict[str, str] = field(default_factory=dict)
    http_use_auth: bool = False
    http_forwarded_for: str = ""


def parse_webstream_msg(data: bytes) -> Optional[WebStreamMsg]:
    """Parse a WebStreamMsg from the raw FlatBuffer bytes (after size prefix)."""
    buf = bytearray(data)
    root = _find_root(buf)
    if root is None:
        return None

    inner = _find_inner_table(buf, root, MessageContext.WebStreamMsg)
    if inner is None:
        return None

    msg = WebStreamMsg()
    msg.stream_id = _read_uint32_field(buf, inner, 0)
    msg.is_open_msg = _read_bool_field(buf, inner, 1)
    msg.is_close_msg = _read_bool_field(buf, inner, 2)
    msg.is_data_transmission_done = _read_bool_field(buf, inner, 3)
    msg.is_control_flags_only = _read_bool_field(buf, inner, 4)
    msg.full_stream_data_size = _read_int64_field(buf, inner, 5)
    msg.data = _read_byte_vector(buf, inner, 6)
    msg.data_compression = _read_int8_field(buf, inner, 7)
    msg.original_data_size = _read_uint64_field(buf, inner, 8)
    msg.status_code = _read_uint16_field(buf, inner, 11)

    # Parse HttpInitialContext if present (slot 9)
    http_ctx_offset = _read_table_offset(buf, inner, 9)
    if http_ctx_offset != 0:
        msg.http_path = _read_string_field(buf, http_ctx_offset, 0)
        msg.http_method = _read_string_field(buf, http_ctx_offset, 2)
        msg.http_use_auth = _read_int8_field(buf, http_ctx_offset, 5) != 0
        msg.http_forwarded_for = _read_string_field(buf, http_ctx_offset, 6)
        # Parse headers (slot 4)
        headers_offset = _read_vector_offset(buf, http_ctx_offset, 4)
        if headers_offset != 0:
            msg.http_headers = _read_http_headers(buf, headers_offset)

    return msg


# ---------------------------------------------------------------------------
# WebStreamMsg response builder
# ---------------------------------------------------------------------------

def build_webstream_response(
    stream_id: int,
    status_code: int,
    body: bytes,
    content_type: str = "application/json",
    extra_headers: Optional[Dict[str, str]] = None,
) -> bytes:
    """Build a WebStreamMsg response (server → client direction).

    Sends the HTTP response with status code, body, and response headers,
    marking the stream as complete (is_close_msg + is_data_transmission_done).
    """
    if extra_headers is None:
        extra_headers = {}
    builder = flatbuffers.Builder(max(512, len(body) + 256))

    body_off = _create_byte_vector(builder, body) if body else 0

    # Build all HTTP header strings and tables BEFORE any parent table starts.
    all_headers: Dict[str, str] = {
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
        "Connection": "close",
    }
    all_headers.update(extra_headers)
    header_offsets = []
    for key, value in all_headers.items():
        k_off = _create_string(builder, key)
        v_off = _create_string(builder, value)
        builder.StartObject(2)
        builder.PrependUOffsetTRelativeSlot(0, k_off, 0)
        builder.PrependUOffsetTRelativeSlot(1, v_off, 0)
        header_offsets.append(builder.EndObject())

    # Build the headers vector
    builder.StartVector(4, len(header_offsets), 4)
    for o in reversed(header_offsets):
        builder.PrependUOffsetTRelative(o)
    hdrs_off = builder.EndVector()

    # Build HttpInitialContext for the response (carries response headers)
    builder.StartObject(7)
    builder.PrependUOffsetTRelativeSlot(4, hdrs_off, 0)
    ctx_off = builder.EndObject()

    # Build WebStreamMsg table
    body_len = len(body)
    builder.StartObject(18)
    builder.PrependUint32Slot(0, stream_id, 0)                      # stream_id
    builder.PrependBoolSlot(1, False, False)                         # is_open_msg
    builder.PrependBoolSlot(2, True, False)                          # is_close_msg
    builder.PrependBoolSlot(3, True, False)                          # is_data_transmission_done
    builder.PrependBoolSlot(4, False, False)                         # is_control_flags_only
    builder.PrependInt64Slot(5, body_len, -1)                        # full_stream_data_size
    builder.PrependUOffsetTRelativeSlot(6, body_off, 0)             # data
    builder.PrependInt8Slot(7, DataCompression.None_, 0)            # data_compression
    builder.PrependUint64Slot(8, 0, 0)                               # original_data_size
    builder.PrependUOffsetTRelativeSlot(9, ctx_off, 0)              # http_initial_context (response headers)
    builder.PrependBoolSlot(10, False, False)                        # is_websocket_stream
    builder.PrependUint16Slot(11, status_code, 0)                   # status_code
    webstream_off = builder.EndObject()

    # Wrap in OctoStreamMessage
    builder.StartObject(2)
    builder.PrependUint8Slot(0, MessageContext.WebStreamMsg, 0)
    builder.PrependUOffsetTRelativeSlot(1, webstream_off, 0)
    root = builder.EndObject()

    builder.FinishSizePrefixed(root)
    return bytes(builder.Output())


# ---------------------------------------------------------------------------
# Low-level FlatBuffer readers
# ---------------------------------------------------------------------------

def _read_u32(buf: bytearray, pos: int) -> int:
    return struct.unpack_from("<I", buf, pos)[0]


def _read_i32(buf: bytearray, pos: int) -> int:
    return struct.unpack_from("<i", buf, pos)[0]


def _read_u64(buf: bytearray, pos: int) -> int:
    return struct.unpack_from("<Q", buf, pos)[0]


def _read_i64(buf: bytearray, pos: int) -> int:
    return struct.unpack_from("<q", buf, pos)[0]


def _read_i8(buf: bytearray, pos: int) -> int:
    return struct.unpack_from("<b", buf, pos)[0]


def _read_u16(buf: bytearray, pos: int) -> int:
    return struct.unpack_from("<H", buf, pos)[0]


def _vtable_offset(buf: bytearray, root: int, slot: int) -> int:
    """Read the field offset from the vtable for a given slot."""
    vtable_pos = root - _read_i32(buf, root)  # vtable offset is stored as negative i32
    vtable_schemas = _read_u16(buf, vtable_pos)  # size of vtable
    vtable_data = _read_u16(buf, vtable_pos + 2)  # size of object data
    field_pos = vtable_pos + 4 + (slot * 2)
    if field_pos + 2 > vtable_pos + vtable_schemas:
        return 0  # slot doesn't exist in this vtable
    field_offset = _read_u16(buf, field_pos)
    if field_offset == 0:
        return 0  # field is default (not present)
    return root + field_offset


def _read_field_offset(buf: bytearray, table: int, slot: int) -> int:
    """Read the absolute position of a field, or 0 if not present."""
    off = _vtable_offset(buf, table, slot)
    return off


def _read_bool_field(buf: bytearray, table: int, slot: int) -> bool:
    off = _read_field_offset(buf, table, slot)
    return bool(buf[off]) if off else False


def _read_int8_field(buf: bytearray, table: int, slot: int) -> int:
    off = _read_field_offset(buf, table, slot)
    return _read_i8(buf, off) if off else 0


def _read_uint16_field(buf: bytearray, table: int, slot: int) -> int:
    off = _read_field_offset(buf, table, slot)
    return _read_u16(buf, off) if off else 0


def _read_uint32_field(buf: bytearray, table: int, slot: int) -> int:
    off = _read_field_offset(buf, table, slot)
    return _read_u32(buf, off) if off else 0


def _read_int64_field(buf: bytearray, table: int, slot: int) -> int:
    off = _read_field_offset(buf, table, slot)
    return _read_i64(buf, off) if off else -1


def _read_uint64_field(buf: bytearray, table: int, slot: int) -> int:
    off = _read_field_offset(buf, table, slot)
    return _read_u64(buf, off) if off else 0


def _read_string_field(buf: bytearray, table: int, slot: int) -> str:
    off = _read_field_offset(buf, table, slot)
    if not off:
        return ""
    str_off = _read_u32(buf, off)  # uoffset to string
    str_abs = off + str_off
    str_len = _read_u32(buf, str_abs)
    return buf[str_abs + 4:str_abs + 4 + str_len].decode("utf-8", errors="replace")


def _read_table_offset(buf: bytearray, table: int, slot: int) -> int:
    """Return the absolute position of a nested table, or 0."""
    off = _read_field_offset(buf, table, slot)
    if not off:
        return 0
    inner = _read_u32(buf, off)  # uoffset to inner table
    return off + inner


def _read_vector_offset(buf: bytearray, table: int, slot: int) -> int:
    """Return the absolute position of a vector, or 0."""
    off = _read_field_offset(buf, table, slot)
    if not off:
        return 0
    vec_off = _read_u32(buf, off)
    return off + vec_off


def _read_byte_vector(buf: bytearray, table: int, slot: int) -> bytes:
    off = _read_vector_offset(buf, table, slot)
    if not off:
        return b""
    vec_len = _read_u32(buf, off)
    return bytes(buf[off + 4:off + 4 + vec_len])


def _read_string_vector(buf: bytearray, table: int, slot: int) -> List[str]:
    off = _read_vector_offset(buf, table, slot)
    if not off:
        return []
    vec_len = _read_u32(buf, off)
    result = []
    for i in range(vec_len):
        elem_pos = off + 4 + (i * 4)  # each element is a uoffset (4 bytes)
        str_uoffset = _read_u32(buf, elem_pos)
        str_abs = elem_pos + str_uoffset
        str_len = _read_u32(buf, str_abs)
        result.append(buf[str_abs + 4:str_abs + 4 + str_len].decode("utf-8", errors="replace"))
    return result


def _read_http_headers(buf: bytearray, vec_off: int) -> Dict[str, str]:
    """Parse a vector of HttpHeader tables."""
    vec_len = _read_u32(buf, vec_off)
    headers = {}
    for i in range(vec_len):
        elem_pos = vec_off + 4 + (i * 4)
        tbl_uoffset = _read_u32(buf, elem_pos)
        tbl_abs = elem_pos + tbl_uoffset
        key = _read_string_field(buf, tbl_abs, 0)
        val = _read_string_field(buf, tbl_abs, 1)
        headers[key] = val
    return headers


def _find_root(buf: bytearray) -> Optional[int]:
    """Read the uoffset at position 0 to find the root table position."""
    if len(buf) < 4:
        return None
    uoffset = _read_u32(buf, 0)
    root = uoffset  # uoffset is absolute from position 0
    if root + 4 > len(buf):
        return None
    return root


def _find_inner_table(buf: bytearray, root: int, expected_context_type: int) -> Optional[int]:
    """Find the inner message table inside an OctoStreamMessage.

    Args:
        buf: The FlatBuffer payload (after size prefix).
        root: Absolute position of the root OctoStreamMessage table.
        expected_context_type: The MessageContext enum value expected.

    Returns the absolute position of the inner table, or None.
    """
    # context_type is slot 0 of OctoStreamMessage
    ctx_type = _read_u8(buf, _vtable_offset(buf, root, 0)) if _vtable_offset(buf, root, 0) else 0
    if ctx_type != expected_context_type:
        return None

    # context union is slot 1
    return _read_table_offset(buf, root, 1)


def _read_u8(buf: bytearray, pos: int) -> int:
    return buf[pos]


# ---------------------------------------------------------------------------
# Size prefix handling
# ---------------------------------------------------------------------------

def strip_size_prefix(data: bytes) -> bytes:
    """Remove the 4-byte LE uint32 size prefix from a message."""
    if len(data) < 4:
        return data
    size = struct.unpack_from("<I", data, 0)[0]
    return data[4:4 + size]


def add_size_prefix(flatbuf_data: bytes) -> bytes:
    """Add a 4-byte LE uint32 size prefix (the flatbuffers library's
    FinishSizePrefixed already does this, so this is for reference)."""
    size = len(flatbuf_data)
    return struct.pack("<I", size) + flatbuf_data
