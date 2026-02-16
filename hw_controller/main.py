"""
Photobooth Hardware Controller — main entry point.

Binds all subsystems:
  - ZeroMQ IPC server (ROUTER + PUB)
  - State machine
  - Camera & Printer controllers
  - SQLite database
  - Background sync worker

Spawn this from Electron via:
    child_process.spawn("python", ["-m", "hw_controller.main"])
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from hw_controller.config import (
    DATA_DIR,
    DB_PATH,
    LOG_LEVEL,
    SESSION_DIR,
    ZMQ_PUB_PORT,
    ZMQ_RPC_PORT,
    CAMERA_RECONNECT_ATTEMPTS,
    CAMERA_RECONNECT_INTERVAL,
)
from hw_controller.core.state_machine import BoothStateMachine, State, Trigger
from hw_controller.core.session import SessionManager
from hw_controller.core.sync_worker import SyncWorker
from hw_controller.db.database import Database
from hw_controller.hardware.camera import CameraController, CameraDisconnectedError
from hw_controller.hardware.printer import PrinterController
from hw_controller.ipc.server import IPCServer

logger = logging.getLogger("hw_controller")


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


class Application:
    """Top-level application that wires everything together."""

    def __init__(self):
        # Ensure data directories exist
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SESSION_DIR.mkdir(parents=True, exist_ok=True)

        # Database
        self.db = Database(DB_PATH)
        self.db.create_tables()

        # Hardware
        self.camera = CameraController(
            download_dir=SESSION_DIR,
            max_reconnect_attempts=CAMERA_RECONNECT_ATTEMPTS,
            reconnect_interval=CAMERA_RECONNECT_INTERVAL,
        )
        self.printer = PrinterController()

        # IPC
        self.ipc = IPCServer(rpc_port=ZMQ_RPC_PORT, pub_port=ZMQ_PUB_PORT)

        # State machine — broadcasts state changes via IPC PUB
        self.state_machine = BoothStateMachine(on_transition=self._on_state_transition)

        # Session manager
        self.session_mgr = SessionManager(
            state_machine=self.state_machine,
            camera=self.camera,
            printer=self.printer,
            db=self.db,
        )

        # Sync worker
        self.sync_worker = SyncWorker(self.db)

        # Register RPC handlers
        self._register_handlers()

    # ── State transition callback → IPC event ───────────────────────

    async def _on_state_transition(self, prev, next_state, trigger, context):
        """Broadcast every state change to Electron via PUB socket."""
        await self.ipc.publish_event("state_changed", {
            "from": prev.value,
            "to": next_state.value,
            "trigger": trigger.value,
            "context": context or {},
        })

    # ── RPC Handler registration ────────────────────────────────────

    def _register_handlers(self):
        """Register all JSON-RPC methods."""

        # -- System --
        self.ipc.register("system.status", self._handle_system_status)
        self.ipc.register("system.state", self._handle_system_state)

        # -- Camera --
        self.ipc.register("camera.connect", self._handle_camera_connect)
        self.ipc.register("camera.disconnect", self._handle_camera_disconnect)
        self.ipc.register("camera.status", self._handle_camera_status)

        # -- Session --
        self.ipc.register("session.start", self._handle_session_start)
        self.ipc.register("session.cancel", self._handle_session_cancel)
        self.ipc.register("session.complete", self._handle_session_complete)
        self.ipc.register("session.capture", self._handle_session_capture)
        self.ipc.register("session.next_photo", self._handle_session_next_photo)

        # -- Printing --
        self.ipc.register("printer.print", self._handle_print)
        self.ipc.register("printer.list", self._handle_printer_list)

    # ── RPC Handlers ────────────────────────────────────────────────

    async def _handle_system_status(self, params: dict) -> dict:
        return {
            "state": self.state_machine.state.value,
            "camera_connected": self.camera.is_connected,
            "session_id": self.session_mgr.session_id,
        }

    async def _handle_system_state(self, params: dict) -> dict:
        return self.state_machine.to_dict()

    async def _handle_camera_connect(self, params: dict) -> dict:
        return await asyncio.to_thread(self.camera.connect)

    async def _handle_camera_disconnect(self, params: dict) -> dict:
        await asyncio.to_thread(self.camera.disconnect)
        return {"status": "disconnected"}

    async def _handle_camera_status(self, params: dict) -> dict:
        return {"connected": self.camera.is_connected}

    async def _handle_session_start(self, params: dict) -> dict:
        return await self.session_mgr.start_session(
            event_name=params.get("event_name"),
            photos_per_session=params.get("photos_per_session"),
            countdown_seconds=params.get("countdown_seconds"),
        )

    async def _handle_session_cancel(self, params: dict) -> dict:
        return await self.session_mgr.cancel_session()

    async def _handle_session_complete(self, params: dict) -> dict:
        return await self.session_mgr.complete_session()

    async def _handle_session_capture(self, params: dict) -> dict:
        return await self.session_mgr.capture()

    async def _handle_session_next_photo(self, params: dict) -> dict:
        return await self.session_mgr.next_photo()

    async def _handle_print(self, params: dict) -> dict:
        file_path = params.get("file_path", "")
        copies = params.get("copies", 1)
        return await self.session_mgr.print_photo(file_path, copies)

    async def _handle_printer_list(self, params: dict) -> dict:
        printers = await asyncio.to_thread(PrinterController.list_printers)
        return {"printers": printers}

    # ── Run ─────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Start all subsystems and block until shutdown."""
        logger.info("━━━ Photobooth HW Controller starting ━━━")

        # Initialise hardware
        try:
            await asyncio.to_thread(self.camera.connect)
            camera_ok = True
        except CameraDisconnectedError as e:
            logger.warning("Camera not available at startup: %s", e)
            camera_ok = False

        # Transition out of INITIALIZING
        if camera_ok:
            await self.state_machine.fire(Trigger.HARDWARE_READY, {
                "cameras": 1 if camera_ok else 0,
                "printers": len(PrinterController.list_printers()),
            })
        else:
            await self.state_machine.fire(Trigger.HARDWARE_FAIL, {
                "error": "No camera detected",
            })

        # Start background services
        self.sync_worker.start()

        # Publish ready event
        await self.ipc.publish_event("ready", {
            "state": self.state_machine.state.value,
            "camera_connected": camera_ok,
        })

        # Run IPC server (blocks)
        try:
            await self.ipc.run()
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        """Clean up all resources."""
        logger.info("Shutting down…")
        await self.sync_worker.stop()
        await asyncio.to_thread(self.camera.disconnect)
        await self.ipc.shutdown()
        logger.info("━━━ Photobooth HW Controller stopped ━━━")


async def main() -> None:
    app = Application()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(_graceful_exit(app)))
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler

    await app.run()


async def _graceful_exit(app: Application) -> None:
    await app._shutdown()
    sys.exit(0)


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
