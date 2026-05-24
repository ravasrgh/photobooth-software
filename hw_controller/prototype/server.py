"""
Photobooth Prototype Server.

Serves the prototype web UI and provides REST API endpoints backed by the
real FSM, database, and (optionally) DSLR camera hardware.

Run:    cd <project_root> && .venv/bin/python -m hw_controller.prototype.server
Open:   http://localhost:8888
"""

import asyncio
import base64
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aiohttp import web

# ── Path setup ──────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hw_controller.core.state_machine import (
    BoothStateMachine, State, Trigger, InvalidTransitionError,
)
from hw_controller.db.database import Database
from hw_controller.db.models import (
    Session as DBSession, Payment, Media, FrameConfig, SyncJob,
)
from hw_controller.config import (
    DATA_DIR, SESSION_DIR, DB_PATH,
    DEFAULT_PHOTOS_PER_SESSION, DEFAULT_COUNTDOWN_SECONDS,
)

# ── Optional imports ────────────────────────────────────────────────
try:
    from hw_controller.hardware.camera import CameraController, CameraDisconnectedError
    from hw_controller.hardware.preview import PreviewServer
    _HAS_CAMERA_MODULE = True
except ImportError:
    _HAS_CAMERA_MODULE = False

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PILLOW = True
except ImportError:
    _HAS_PILLOW = False

logger = logging.getLogger("prototype")

PORT = int(os.getenv("PB_PROTOTYPE_PORT", "8888"))
PAYMENT_AUTO_CONFIRM_DELAY = 3   # seconds
PRINT_SIMULATE_DELAY = 2         # seconds


class PrototypeApp:
    """Photobooth prototype — combines real FSM + DB with mock hardware."""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SESSION_DIR.mkdir(parents=True, exist_ok=True)

        self.db = Database(DB_PATH)
        self.db.create_tables()
        self.fsm = BoothStateMachine()

        # Camera
        self.camera: Optional[CameraController] = None
        self.camera_available = False
        self.preview_server: Optional[PreviewServer] = None
        self.preview_url: Optional[str] = None

        # Session state
        self.session_id: Optional[str] = None
        self.photo_index: int = 0
        self.photos_target: int = DEFAULT_PHOTOS_PER_SESSION
        self.countdown_seconds: int = DEFAULT_COUNTDOWN_SECONDS
        self.photos: list[dict] = []
        self.layout_id: str = "strip_vertical"
        self.design_id: str = "classic_white"
        self._payment_task: Optional[asyncio.Task] = None

    # ── Lifecycle ───────────────────────────────────────────────────

    async def startup(self):
        if _HAS_CAMERA_MODULE:
            try:
                from hw_controller.config import PREVIEW_PORT, PREVIEW_FPS, PREVIEW_QUALITY
                self.camera = CameraController(
                    download_dir=SESSION_DIR,
                    max_reconnect_attempts=2,
                    reconnect_interval=1.0,
                )
                self.camera.connect()
                self.camera_available = True
                self.preview_server = PreviewServer(
                    port=PREVIEW_PORT, fps=PREVIEW_FPS, quality=PREVIEW_QUALITY,
                )
                await self.preview_server.start(self.camera)
                self.preview_url = self.preview_server.url
                logger.info("DSLR camera connected, preview at %s", self.preview_url)
            except Exception as e:
                logger.info("No DSLR camera: %s (using webcam/mock fallback)", e)
                self.camera_available = False
                self.camera = None

        await self.fsm.fire(Trigger.HARDWARE_READY)
        logger.info("FSM ready: %s", self.fsm.state.value)

    async def shutdown(self):
        if self.preview_server and self.preview_server.is_running:
            await self.preview_server.stop()
        if self.camera:
            self.camera.disconnect()

    def _reset_session(self):
        self.session_id = None
        self.photo_index = 0
        self.photos = []
        self.layout_id = "strip_vertical"
        self.design_id = "classic_white"
        if self._payment_task and not self._payment_task.done():
            self._payment_task.cancel()

    # ── Photo generation ────────────────────────────────────────────

    def _generate_mock_photo(self, session_id: str, index: int) -> Path:
        dest = SESSION_DIR / session_id
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"photo_{index:03d}.jpg"
        if _HAS_PILLOW:
            colors = [
                (220, 228, 240), (232, 220, 238), (220, 238, 225),
                (242, 228, 218), (218, 235, 238), (238, 235, 218),
            ]
            bg = colors[(index - 1) % len(colors)]
            img = Image.new("RGB", (800, 600), color=bg)
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
                sfont = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
            except OSError:
                font = ImageFont.load_default()
                sfont = font
            text = f"Photo {index}"
            bb = draw.textbbox((0, 0), text, font=font)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            draw.text(((800 - tw) // 2, (600 - th) // 2 - 15), text,
                      fill=(120, 120, 120), font=font)
            sub = datetime.now().strftime("%H:%M:%S")
            bb2 = draw.textbbox((0, 0), sub, font=sfont)
            tw2 = bb2[2] - bb2[0]
            draw.text(((800 - tw2) // 2, (600 + th) // 2 + 15), sub,
                      fill=(170, 170, 170), font=sfont)
            img.save(path, "JPEG", quality=90)
        else:
            path.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 100 + b'\xff\xd9')
        return path

    def _save_webcam_frame(self, session_id: str, index: int, b64: str) -> Path:
        dest = SESSION_DIR / session_id
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"photo_{index:03d}.jpg"
        raw = b64.split(",", 1)[-1] if "," in b64 else b64
        path.write_bytes(base64.b64decode(raw))
        return path

    # ── API Handlers ────────────────────────────────────────────────

    async def handle_status(self, req):
        return web.json_response({
            "state": self.fsm.state.value,
            "session_id": self.session_id,
            "photo_index": self.photo_index,
            "photos_target": self.photos_target,
            "photos_remaining": max(0, self.photos_target - self.photo_index),
            "photos": self.photos,
            "layout_id": self.layout_id,
            "design_id": self.design_id,
            "camera_available": self.camera_available,
            "preview_url": self.preview_url,
        })

    async def handle_session_start(self, req):
        if self.fsm.state != State.IDLE:
            return web.json_response(
                {"error": f"Cannot start from {self.fsm.state.value}"}, status=400)
        self._reset_session()
        self.session_id = str(uuid.uuid4())
        with self.db.session_scope() as s:
            s.add(DBSession(
                id=self.session_id, event_name="Prototype Session",
                photos_target=self.photos_target,
            ))
        await self.fsm.fire(Trigger.SESSION_START, {"session_id": self.session_id})
        return web.json_response({
            "session_id": self.session_id, "state": self.fsm.state.value,
            "photos_target": self.photos_target,
        })

    async def handle_onboarding_complete(self, req):
        await self.fsm.fire(Trigger.ONBOARDING_DONE, {"session_id": self.session_id})
        return web.json_response({"state": self.fsm.state.value})

    async def handle_payment_initiate(self, req):
        body = await req.json() if req.content_length else {}
        method = body.get("method", "qris")
        payment_id = str(uuid.uuid4())
        with self.db.session_scope() as s:
            s.add(Payment(
                id=payment_id, session_id=self.session_id,
                method=method, amount_target=50000, status="pending",
            ))
        self._payment_task = asyncio.create_task(
            self._auto_confirm_payment(payment_id))
        return web.json_response({
            "payment_id": payment_id, "method": method,
            "amount_target": 50000, "status": "pending",
            "auto_confirm_in": PAYMENT_AUTO_CONFIRM_DELAY,
        })

    async def _auto_confirm_payment(self, payment_id: str):
        await asyncio.sleep(PAYMENT_AUTO_CONFIRM_DELAY)
        try:
            with self.db.session_scope() as s:
                pay = s.get(Payment, payment_id)
                if pay:
                    pay.status = "confirmed"
                    pay.amount_received = pay.amount_target
                    pay.confirmed_at = datetime.now(timezone.utc).isoformat()
                sess = s.get(DBSession, self.session_id)
                if sess:
                    sess.status = "paid"
            await self.fsm.fire(Trigger.PAYMENT_CONFIRMED, {
                "session_id": self.session_id, "payment_id": payment_id,
            })
            logger.info("Payment %s auto-confirmed", payment_id[:8])
        except Exception as e:
            logger.error("Auto-confirm failed: %s", e)

    async def handle_capture_ready(self, req):
        await self.fsm.fire(Trigger.CAPTURE_SETUP_READY,
                            {"session_id": self.session_id})
        return web.json_response({
            "state": self.fsm.state.value,
            "countdown_seconds": self.countdown_seconds,
        })

    async def handle_capture_take(self, req):
        body = await req.json() if req.content_length else {}
        image_data = body.get("image_data")

        # COUNTDOWN -> CAPTURING
        await self.fsm.fire(Trigger.COUNTDOWN_DONE, {"session_id": self.session_id})
        self.photo_index += 1

        # Capture
        if self.camera_available and self.camera:
            result = await asyncio.to_thread(
                self.camera.trigger_capture, self.session_id, self.photo_index)
            file_path = result.file_path
            width, height = result.width, result.height
            file_size = result.file_size_bytes
        elif image_data:
            file_path = self._save_webcam_frame(
                self.session_id, self.photo_index, image_data)
            width, height, file_size = 640, 480, file_path.stat().st_size
            if _HAS_PILLOW:
                try:
                    with Image.open(file_path) as img:
                        width, height = img.size
                except Exception:
                    pass
        else:
            file_path = self._generate_mock_photo(
                self.session_id, self.photo_index)
            width, height = 800, 600
            file_size = file_path.stat().st_size

        # DB record
        with self.db.session_scope() as s:
            s.add(Media(
                session_id=self.session_id, photo_index=self.photo_index,
                slot_index=self.photo_index, file_path=str(file_path),
                file_size_bytes=file_size, width=width, height=height,
            ))
            sess = s.get(DBSession, self.session_id)
            if sess:
                sess.photo_count = self.photo_index
                sess.status = "capturing"

        photo_url = f"/photos/{self.session_id}/{file_path.name}"
        self.photos.append({
            "index": self.photo_index, "url": photo_url, "filter_id": "original",
        })

        # CAPTURING -> PROCESSING
        await self.fsm.fire(Trigger.CAPTURE_DONE, {
            "session_id": self.session_id, "photo_index": self.photo_index,
        })

        # PROCESSING -> next
        remaining = self.photos_target - self.photo_index
        if remaining > 0:
            await self.fsm.fire(Trigger.NEXT_PHOTO, {"session_id": self.session_id})
        else:
            await self.fsm.fire(Trigger.ALL_PHOTOS_DONE, {"session_id": self.session_id})

        return web.json_response({
            "state": self.fsm.state.value,
            "photo_index": self.photo_index,
            "photo_url": photo_url,
            "photos_remaining": remaining,
            "photos": self.photos,
        })

    async def handle_customize_layout(self, req):
        body = await req.json()
        self.layout_id = body.get("layout_id", self.layout_id)
        with self.db.session_scope() as s:
            sess = s.get(DBSession, self.session_id)
            if sess:
                sess.layout_id = self.layout_id
        return web.json_response({"layout_id": self.layout_id, "applied": True})

    async def handle_customize_design(self, req):
        body = await req.json()
        self.design_id = body.get("design_id", self.design_id)
        with self.db.session_scope() as s:
            sess = s.get(DBSession, self.session_id)
            if sess:
                sess.design_id = self.design_id
        return web.json_response({"design_id": self.design_id, "applied": True})

    async def handle_customize_filter(self, req):
        body = await req.json()
        idx = body.get("photo_index", 1)
        fid = body.get("filter_id", "original")
        for p in self.photos:
            if p["index"] == idx:
                p["filter_id"] = fid
        with self.db.session_scope() as s:
            media = s.query(Media).filter_by(
                session_id=self.session_id, photo_index=idx).first()
            if media:
                media.filter_id = fid
        return web.json_response({"photo_index": idx, "filter_id": fid, "applied": True})

    async def handle_capture_retake(self, req):
        """Retake a specific photo during customization (no FSM transition)."""
        body = await req.json() if req.content_length else {}
        idx = body.get("photo_index", 1)
        image_data = body.get("image_data")

        # Capture new photo
        if self.camera_available and self.camera:
            result = await asyncio.to_thread(
                self.camera.trigger_capture, self.session_id, idx)
            file_path = result.file_path
            width, height = result.width, result.height
            file_size = result.file_size_bytes
        elif image_data:
            file_path = self._save_webcam_frame(self.session_id, idx, image_data)
            width, height, file_size = 640, 480, file_path.stat().st_size
            if _HAS_PILLOW:
                try:
                    with Image.open(file_path) as img:
                        width, height = img.size
                except Exception:
                    pass
        else:
            file_path = self._generate_mock_photo(self.session_id, idx)
            width, height = 800, 600
            file_size = file_path.stat().st_size

        # Update DB
        with self.db.session_scope() as s:
            media = s.query(Media).filter_by(
                session_id=self.session_id, photo_index=idx).first()
            if media:
                media.file_path = str(file_path)
                media.file_size_bytes = file_size
                media.width = width
                media.height = height
                media.filter_id = "original"

        # Update in-memory photo list
        photo_url = f"/photos/{self.session_id}/{file_path.name}"
        for p in self.photos:
            if p["index"] == idx:
                p["url"] = photo_url
                p["filter_id"] = "original"

        logger.info("Retook photo %d for session %s", idx, self.session_id[:8])
        return web.json_response({
            "state": self.fsm.state.value,
            "photo_index": idx,
            "photo_url": photo_url,
            "photos": self.photos,
        })

    async def handle_customize_confirm(self, req):
        with self.db.session_scope() as s:
            existing = s.query(FrameConfig).filter_by(
                session_id=self.session_id).first()
            order_json = json.dumps([p["index"] for p in self.photos])
            if not existing:
                s.add(FrameConfig(
                    session_id=self.session_id, layout_id=self.layout_id,
                    design_id=self.design_id, photo_order_json=order_json,
                ))
            else:
                existing.layout_id = self.layout_id
                existing.design_id = self.design_id
                existing.photo_order_json = order_json
                existing.updated_at = datetime.now(timezone.utc).isoformat()
            sess = s.get(DBSession, self.session_id)
            if sess:
                sess.status = "customizing"
        await self.fsm.fire(Trigger.CUSTOMIZATION_DONE, {"session_id": self.session_id})
        return web.json_response({"state": self.fsm.state.value})

    async def handle_preview_back(self, req):
        await self.fsm.fire(Trigger.BACK_TO_CUSTOMIZE, {"session_id": self.session_id})
        return web.json_response({"state": self.fsm.state.value})

    async def handle_print_request(self, req):
        await self.fsm.fire(Trigger.PRINT_REQUESTED, {"session_id": self.session_id})
        await asyncio.sleep(PRINT_SIMULATE_DELAY)
        with self.db.session_scope() as s:
            sess = s.get(DBSession, self.session_id)
            if sess:
                sess.status = "printing"
                sess.download_token = uuid.uuid4().hex[:16]
            s.add(SyncJob(
                session_id=self.session_id,
                job_type="upload_composite", status="pending",
            ))
        await self.fsm.fire(Trigger.PRINT_DONE, {"session_id": self.session_id})
        return web.json_response({"state": self.fsm.state.value, "status": "printed"})

    async def handle_session_complete(self, req):
        sid = self.session_id
        with self.db.session_scope() as s:
            sess = s.get(DBSession, sid)
            if sess:
                sess.status = "completed"
                sess.completed_at = datetime.now(timezone.utc).isoformat()
        await self.fsm.fire(Trigger.SESSION_COMPLETE, {"session_id": sid})
        self._reset_session()
        return web.json_response({"state": self.fsm.state.value})

    async def handle_session_cancel(self, req):
        sid = self.session_id
        if sid:
            with self.db.session_scope() as s:
                sess = s.get(DBSession, sid)
                if sess:
                    sess.status = "cancelled"
                    sess.completed_at = datetime.now(timezone.utc).isoformat()
        if self.fsm.can_fire(Trigger.SESSION_CANCEL):
            await self.fsm.fire(Trigger.SESSION_CANCEL)
        elif self.fsm.can_fire(Trigger.PAYMENT_CANCELLED):
            await self.fsm.fire(Trigger.PAYMENT_CANCELLED)
        elif self.fsm.state != State.IDLE:
            self.fsm._state = State.IDLE
        self._reset_session()
        return web.json_response({"state": self.fsm.state.value})

    async def handle_serve_photo(self, req):
        sid = req.match_info["session_id"]
        fn = req.match_info["filename"]
        path = SESSION_DIR / sid / fn
        if not path.exists():
            return web.Response(status=404, text="Not found")
        return web.FileResponse(path)

    async def handle_db_data(self, req):
        tables = {}
        with self.db.session_scope() as s:
            rows = s.query(DBSession).order_by(DBSession.created_at.desc()).limit(20).all()
            tables["sessions"] = [{
                "id": r.id[:8], "status": r.status,
                "photo_count": r.photo_count, "layout_id": r.layout_id,
                "design_id": r.design_id,
            } for r in rows]
            rows = s.query(Payment).order_by(Payment.created_at.desc()).limit(20).all()
            tables["payments"] = [{
                "id": r.id[:8], "method": r.method,
                "amount": r.amount_received, "status": r.status,
            } for r in rows]
            rows = s.query(Media).order_by(Media.captured_at.desc()).limit(20).all()
            tables["media"] = [{
                "id": r.id[:8], "photo_index": r.photo_index,
                "filter_id": r.filter_id, "w": r.width, "h": r.height,
            } for r in rows]
            rows = s.query(FrameConfig).limit(20).all()
            tables["frame_configs"] = [{
                "id": r.id[:8], "layout_id": r.layout_id,
                "design_id": r.design_id,
            } for r in rows]
            rows = s.query(SyncJob).limit(20).all()
            tables["sync_jobs"] = [{
                "id": r.id[:8], "job_type": r.job_type, "status": r.status,
            } for r in rows]
        return web.json_response(tables)


def create_app(proto: PrototypeApp) -> web.Application:
    app = web.Application()
    r = app.router
    r.add_get("/api/status", proto.handle_status)
    r.add_post("/api/session/start", proto.handle_session_start)
    r.add_post("/api/session/cancel", proto.handle_session_cancel)
    r.add_post("/api/session/complete", proto.handle_session_complete)
    r.add_post("/api/onboarding/complete", proto.handle_onboarding_complete)
    r.add_post("/api/payment/initiate", proto.handle_payment_initiate)
    r.add_post("/api/capture/ready", proto.handle_capture_ready)
    r.add_post("/api/capture/take", proto.handle_capture_take)
    r.add_post("/api/capture/retake", proto.handle_capture_retake)
    r.add_post("/api/customize/layout", proto.handle_customize_layout)
    r.add_post("/api/customize/design", proto.handle_customize_design)
    r.add_post("/api/customize/filter", proto.handle_customize_filter)
    r.add_post("/api/customize/confirm", proto.handle_customize_confirm)
    r.add_post("/api/preview/back", proto.handle_preview_back)
    r.add_post("/api/print/request", proto.handle_print_request)
    r.add_get("/api/db/data", proto.handle_db_data)
    r.add_get("/photos/{session_id}/{filename}", proto.handle_serve_photo)
    static_dir = _THIS_DIR / "static"
    r.add_get("/", lambda _: web.FileResponse(static_dir / "index.html"))
    r.add_static("/static/", static_dir)
    return app


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    proto = PrototypeApp()
    await proto.startup()
    app = create_app(proto)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"\n  Photobooth Prototype")
    print(f"  http://localhost:{PORT}")
    print(f"  Camera: {'DSLR' if proto.camera_available else 'webcam/mock'}")
    print(f"  Press Ctrl+C to stop\n")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await proto.shutdown()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
