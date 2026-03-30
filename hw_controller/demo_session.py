"""
DB Session Prototype — step-by-step simulation of a photobooth user session.

Each step creates/updates real SQLite records so you can see the database
populate as a user walks through the flow.

Run:  cd hw_controller && ../.venv/bin/python demo_session.py
Open: http://localhost:8888
"""

import json
import os
import sys
import asyncio
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from aiohttp import web
from hw_controller.db.database import Database
from hw_controller.db.models import (
    Session as DBSession, Payment, Media, FrameConfig, SyncJob,
)

# ── Globals ─────────────────────────────────────────────────────────
db: Database = None
db_path: Path = None
session_data: dict = {}   # active session state


def init_db():
    global db, db_path, session_data
    db_path = Path(_this_dir) / "prototype.db"
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)
    db.create_tables()
    session_data = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Step handlers ───────────────────────────────────────────────────

STEPS = [
    {
        "id": 1,
        "title": "Welcome",
        "desc": "A new user walks up to the photobooth and taps the screen.",
        "action": "Tap to Start",
        "db_note": "No DB changes — this is the attract/idle screen.",
    },
    {
        "id": 2,
        "title": "Session Created",
        "desc": "User starts a session. A new row is inserted into the sessions table.",
        "action": "Start Session",
        "db_note": "INSERT into sessions (id, status='active', photos_target=4)",
    },
    {
        "id": 3,
        "title": "Payment",
        "desc": "User scans QRIS code. Payment record is created, then confirmed.",
        "action": "Confirm Payment",
        "db_note": "INSERT into payments (method='qris', amount=50000, status='confirmed'). UPDATE sessions.status='paid'",
    },
    {
        "id": 4,
        "title": "Capture Setup",
        "desc": "Camera preview starts. User positions themselves.",
        "action": "Ready!",
        "db_note": "UPDATE sessions.status='capturing'",
    },
    {
        "id": 5,
        "title": "Photo 1",
        "desc": "First photo captured and saved.",
        "action": "Capture Photo 1",
        "db_note": "INSERT into media (photo_index=1, slot_index=1). UPDATE sessions.photo_count=1",
    },
    {
        "id": 6,
        "title": "Photo 2",
        "desc": "Second photo captured and saved.",
        "action": "Capture Photo 2",
        "db_note": "INSERT into media (photo_index=2, slot_index=2). UPDATE sessions.photo_count=2",
    },
    {
        "id": 7,
        "title": "Photo 3",
        "desc": "Third photo captured and saved.",
        "action": "Capture Photo 3",
        "db_note": "INSERT into media (photo_index=3, slot_index=3). UPDATE sessions.photo_count=3",
    },
    {
        "id": 8,
        "title": "Photo 4",
        "desc": "Fourth and final photo captured.",
        "action": "Capture Photo 4",
        "db_note": "INSERT into media (photo_index=4, slot_index=4). UPDATE sessions.photo_count=4",
    },
    {
        "id": 9,
        "title": "Customization",
        "desc": "User picks a layout and design for their photo strip.",
        "action": "Confirm Design",
        "db_note": "INSERT into frame_configs (layout, design, photo_order). UPDATE sessions (layout_id, design_id, status='customizing')",
    },
    {
        "id": 10,
        "title": "Print Preview",
        "desc": "Final composite is generated. Download token assigned.",
        "action": "Print!",
        "db_note": "UPDATE sessions (composite_path, download_token, status='printing'). INSERT into sync_queue (upload_composite).",
    },
    {
        "id": 11,
        "title": "Session Complete",
        "desc": "Photo printed! Session marked complete.",
        "action": "Done",
        "db_note": "UPDATE sessions (status='completed', completed_at). INSERT sync_queue (upload_session).",
    },
]


def execute_step(step_id: int) -> dict:
    """Execute the DB operations for a given step."""
    global session_data

    if step_id == 1:
        # Welcome — no DB action
        return {"ok": True}

    elif step_id == 2:
        # Create session
        sid = str(uuid.uuid4())
        session_data = {"id": sid, "photo_count": 0}
        with db.session_scope() as s:
            s.add(DBSession(
                id=sid,
                event_name="User Session",
                status="active",
                photos_target=4,
            ))
        return {"ok": True, "session_id": sid[:8]}

    elif step_id == 3:
        # Payment
        sid = session_data.get("id")
        with db.session_scope() as s:
            s.add(Payment(
                session_id=sid,
                method="qris",
                amount_target=50000,
                amount_received=50000,
                status="confirmed",
                transaction_ref=f"TXN-{uuid.uuid4().hex[:8].upper()}",
                qr_code_data="00020101021126...",
                confirmed_at=_now(),
            ))
            sess = s.get(DBSession, sid)
            if sess:
                sess.status = "paid"
        return {"ok": True}

    elif step_id == 4:
        # Capture setup
        sid = session_data.get("id")
        with db.session_scope() as s:
            sess = s.get(DBSession, sid)
            if sess:
                sess.status = "capturing"
        return {"ok": True}

    elif step_id in (5, 6, 7, 8):
        # Photo capture
        idx = step_id - 4  # 1, 2, 3, 4
        sid = session_data.get("id")
        session_data["photo_count"] = idx
        with db.session_scope() as s:
            s.add(Media(
                session_id=sid,
                photo_index=idx,
                slot_index=idx,
                file_path=f"/data/sessions/{sid[:8]}/photo_{idx:03d}.jpg",
                file_size_bytes=4_500_000,
                width=6000,
                height=4000,
                filter_id="original",
            ))
            sess = s.get(DBSession, sid)
            if sess:
                sess.photo_count = idx
        return {"ok": True, "photo_index": idx}

    elif step_id == 9:
        # Customization
        sid = session_data.get("id")
        count = session_data.get("photo_count", 4)
        with db.session_scope() as s:
            s.add(FrameConfig(
                session_id=sid,
                layout_id="strip_2x2",
                design_id="retro_kawaii",
                photo_order_json=json.dumps(list(range(1, count + 1))),
                custom_text=None,
            ))
            sess = s.get(DBSession, sid)
            if sess:
                sess.layout_id = "strip_2x2"
                sess.design_id = "retro_kawaii"
                sess.status = "customizing"
        return {"ok": True}

    elif step_id == 10:
        # Print preview + print
        sid = session_data.get("id")
        token = f"dl_{uuid.uuid4().hex[:12]}"
        with db.session_scope() as s:
            sess = s.get(DBSession, sid)
            if sess:
                sess.composite_path = f"/data/sessions/{sid[:8]}/composite.jpg"
                sess.download_token = token
                sess.status = "printing"
            s.add(SyncJob(
                session_id=sid,
                job_type="upload_composite",
                status="pending",
            ))
        return {"ok": True, "download_token": token}

    elif step_id == 11:
        # Complete
        sid = session_data.get("id")
        with db.session_scope() as s:
            sess = s.get(DBSession, sid)
            if sess:
                sess.status = "completed"
                sess.completed_at = _now()
            s.add(SyncJob(
                session_id=sid,
                job_type="upload_session",
                status="pending",
            ))
        session_data = {}
        return {"ok": True}

    return {"ok": False, "error": "Unknown step"}


# ── API handlers ────────────────────────────────────────────────────

async def handle_steps(request):
    return web.json_response(STEPS)

async def handle_execute(request):
    body = await request.json()
    step_id = body.get("step")
    result = execute_step(step_id)
    return web.json_response(result)

async def handle_db_data(request):
    tables = {}
    with db.session_scope() as s:
        rows = s.query(DBSession).all()
        tables["sessions"] = [{
            "id": r.id[:8] + "...", "event_name": r.event_name,
            "status": r.status, "photo_count": r.photo_count,
            "photos_target": r.photos_target, "layout_id": r.layout_id,
            "design_id": r.design_id,
            "composite_path": (r.composite_path or "")[-25:] or None,
            "download_token": r.download_token,
            "created_at": r.created_at[:19] if r.created_at else None,
            "completed_at": r.completed_at[:19] if r.completed_at else None,
        } for r in rows]

        rows = s.query(Payment).all()
        tables["payments"] = [{
            "id": r.id[:8] + "...", "session_id": r.session_id[:8] + "...",
            "method": r.method, "amount_target": r.amount_target,
            "amount_received": r.amount_received, "status": r.status,
            "transaction_ref": r.transaction_ref,
        } for r in rows]

        rows = s.query(Media).all()
        tables["media"] = [{
            "id": r.id[:8] + "...", "session_id": r.session_id[:8] + "...",
            "photo_index": r.photo_index, "slot_index": r.slot_index,
            "file_path": r.file_path.split("/")[-1] if r.file_path else None,
            "filter_id": r.filter_id, "is_retake": r.is_retake,
            "width": r.width, "height": r.height,
        } for r in rows]

        rows = s.query(FrameConfig).all()
        tables["frame_configs"] = [{
            "id": r.id[:8] + "...", "session_id": r.session_id[:8] + "...",
            "layout_id": r.layout_id, "design_id": r.design_id,
            "photo_order_json": r.photo_order_json, "custom_text": r.custom_text,
        } for r in rows]

        rows = s.query(SyncJob).all()
        tables["sync_queue"] = [{
            "id": r.id[:8] + "...",
            "session_id": (r.session_id[:8] + "...") if r.session_id else None,
            "media_id": (r.media_id[:8] + "...") if r.media_id else None,
            "job_type": r.job_type, "status": r.status, "attempts": r.attempts,
        } for r in rows]

    return web.json_response(tables)

async def handle_reset(request):
    init_db()
    return web.json_response({"ok": True})

async def handle_export(request):
    """Download the current prototype.db file."""
    if db_path and db_path.exists():
        return web.FileResponse(db_path, headers={
            "Content-Disposition": "attachment; filename=prototype.db"
        })
    return web.json_response({"error": "No database"}, status=404)

async def handle_index(request):
    return web.FileResponse(os.path.join(_this_dir, "demo_session.html"))


# ── Main ────────────────────────────────────────────────────────────

async def _start_app():
    init_db()
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/steps", handle_steps)
    app.router.add_post("/api/execute", handle_execute)
    app.router.add_get("/api/db/data", handle_db_data)
    app.router.add_post("/api/reset", handle_reset)
    app.router.add_get("/api/export", handle_export)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8888)
    await site.start()

    print("Photobooth DB Session Prototype")
    print("  http://localhost:8888")
    print("  Press Ctrl+C to stop\n")
    return runner

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    runner = loop.run_until_complete(_start_app())
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        loop.run_until_complete(runner.cleanup())
        loop.close()
