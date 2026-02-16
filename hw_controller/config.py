"""
Centralised configuration for the Photobooth Hardware Controller.

All tuneable constants live here so they can be overridden via
environment variables without touching code.
"""

import os
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(os.getenv("PB_BASE_DIR", Path(__file__).resolve().parent.parent))
DATA_DIR = BASE_DIR / "data"
SESSION_DIR = DATA_DIR / "sessions"
DB_PATH = DATA_DIR / "photobooth.db"

# ── ZeroMQ Ports ─────────────────────────────────────────────────────
ZMQ_RPC_PORT = int(os.getenv("PB_ZMQ_RPC_PORT", "5555"))
ZMQ_PUB_PORT = int(os.getenv("PB_ZMQ_PUB_PORT", "5556"))

# ── Camera ───────────────────────────────────────────────────────────
CAMERA_RECONNECT_ATTEMPTS = int(os.getenv("PB_CAMERA_RECONNECT_ATTEMPTS", "5"))
CAMERA_RECONNECT_INTERVAL = float(os.getenv("PB_CAMERA_RECONNECT_INTERVAL", "2.0"))

# ── Session defaults ─────────────────────────────────────────────────
DEFAULT_PHOTOS_PER_SESSION = int(os.getenv("PB_PHOTOS_PER_SESSION", "4"))
DEFAULT_COUNTDOWN_SECONDS = int(os.getenv("PB_COUNTDOWN_SECONDS", "3"))

# ── Printer ──────────────────────────────────────────────────────────
PRINT_TIMEOUT_SECONDS = int(os.getenv("PB_PRINT_TIMEOUT", "30"))

# ── Sync ─────────────────────────────────────────────────────────────
SYNC_MAX_ATTEMPTS = int(os.getenv("PB_SYNC_MAX_ATTEMPTS", "5"))
SYNC_POLL_INTERVAL = float(os.getenv("PB_SYNC_POLL_INTERVAL", "30.0"))

# ── Logging ──────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("PB_LOG_LEVEL", "INFO")
