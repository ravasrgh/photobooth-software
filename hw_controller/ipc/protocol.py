"""JSON-RPC 2.0 protocol helpers — parsing requests and building responses."""

from typing import Any, Optional


class JsonRpcError(Exception):
    """Structured error for JSON-RPC responses."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


# ── Standard JSON-RPC error codes ───────────────────────────────────
PARSE_ERROR      = -32700
INVALID_REQUEST  = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS   = -32602
INTERNAL_ERROR   = -32603

# ── Application error codes (custom range) ──────────────────────────
CAMERA_ERROR     = -32001
PRINTER_ERROR    = -32002
STATE_ERROR      = -32003


def parse_request(raw: bytes) -> dict:
    """Parse a raw JSON-RPC request.

    Returns:
        dict with "jsonrpc", "id", "method", and optional "params".

    Raises:
        JsonRpcError: on parse or validation failure.
    """
    import json

    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise JsonRpcError(PARSE_ERROR, f"Parse error: {e}")

    if not isinstance(msg, dict):
        raise JsonRpcError(INVALID_REQUEST, "Request must be a JSON object")

    if "method" not in msg:
        raise JsonRpcError(INVALID_REQUEST, "Missing 'method' field")

    return msg


def success_response(req_id: Optional[str], result: Any) -> dict:
    """Build a JSON-RPC success response."""
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def error_response(
    req_id: Optional[str],
    code: int,
    message: str,
    data: Any = None,
) -> dict:
    """Build a JSON-RPC error response."""
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def event_message(event_name: str, data: dict) -> dict:
    """Build an event payload for the PUB channel."""
    return {"event": event_name, "data": data}
