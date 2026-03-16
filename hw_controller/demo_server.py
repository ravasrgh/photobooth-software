"""
FSM + Database Demo Server.

As you click through FSM states, real database records are created:
  session_start    → creates a Session row
  payment_confirmed → creates a Payment row
  capture_done     → creates a Media row
  customization_done → creates a FrameConfig row
  print_done       → creates a SyncJob row

Run:  cd hw_controller && ../.venv/bin/python demo_server.py
Open: http://localhost:8888
"""

import json
import os
import sys
import asyncio
import tempfile

_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from pathlib import Path
from aiohttp import web
from hw_controller.core.state_machine import (
    BoothStateMachine, InvalidTransitionError, State, Trigger, TRANSITIONS
)
from hw_controller.db.database import Database
from hw_controller.db.models import Session as DBSession, Payment, Media, FrameConfig, SyncJob

# ── Globals ─────────────────────────────────────────────────────────
machine = BoothStateMachine()
transition_log: list[dict] = []
db: Database = None
current_session_id: str | None = None
photo_counter: int = 0

def init_db():
    global db
    db_path = Path(tempfile.mkdtemp()) / "demo.db"
    db = Database(db_path)
    db.create_tables()

def build_transitions():
    out = []
    for (src, trigger), dst in TRANSITIONS.items():
        out.append({"from": src.value, "to": dst.value, "trigger": trigger.value})
    return out

ALL_TRANSITIONS = build_transitions()


# ── DB side-effects per transition ──────────────────────────────────
def on_transition(prev_state: str, trigger: str, new_state: str):
    """Create DB records based on certain transitions."""
    global current_session_id, photo_counter

    if trigger == "session_start":
        with db.session_scope() as s:
            sess = DBSession(event_name="Demo Session", photos_target=4)
            s.add(sess)
            s.flush()
            current_session_id = sess.id
            photo_counter = 0

    elif trigger == "payment_confirmed" and current_session_id:
        with db.session_scope() as s:
            s.add(Payment(
                session_id=current_session_id,
                method="qris",
                amount_target=50000,
                amount_received=50000,
                status="confirmed",
                transaction_ref="TXN-DEMO-001",
            ))
            sess = s.get(DBSession, current_session_id)
            if sess:
                sess.status = "paid"

    elif trigger == "capture_done" and current_session_id:
        photo_counter += 1
        with db.session_scope() as s:
            s.add(Media(
                session_id=current_session_id,
                photo_index=photo_counter,
                slot_index=photo_counter,
                file_path=f"/data/sessions/demo/photo_{photo_counter:03d}.jpg",
                file_size_bytes=4_500_000,
                width=6000,
                height=4000,
                filter_id="original",
            ))
            sess = s.get(DBSession, current_session_id)
            if sess:
                sess.photo_count = photo_counter
                sess.status = "capturing"

    elif trigger == "customization_done" and current_session_id:
        with db.session_scope() as s:
            existing = s.query(FrameConfig).filter_by(session_id=current_session_id).first()
            if not existing:
                s.add(FrameConfig(
                    session_id=current_session_id,
                    layout_id="strip_2x2",
                    design_id="retro_kawaii",
                    photo_order_json=json.dumps(list(range(1, photo_counter + 1))),
                    custom_text=None,
                ))
            sess = s.get(DBSession, current_session_id)
            if sess:
                sess.status = "customizing"
                sess.layout_id = "strip_2x2"
                sess.design_id = "retro_kawaii"

    elif trigger == "print_done" and current_session_id:
        with db.session_scope() as s:
            sess = s.get(DBSession, current_session_id)
            if sess:
                sess.status = "printing"
                sess.composite_path = f"/data/sessions/demo/composite.jpg"
                sess.download_token = f"tok_{current_session_id[:8]}"
            s.add(SyncJob(
                session_id=current_session_id,
                job_type="upload_composite",
                status="pending",
            ))

    elif trigger == "session_complete" and current_session_id:
        with db.session_scope() as s:
            sess = s.get(DBSession, current_session_id)
            if sess:
                sess.status = "completed"
        current_session_id = None
        photo_counter = 0


# ── API: FSM ────────────────────────────────────────────────────────
async def handle_status(request):
    data = machine.to_dict()
    data["transitions"] = ALL_TRANSITIONS
    data["log"] = transition_log[-50:]
    return web.json_response(data)

async def handle_fire(request):
    body = await request.json()
    trigger_name = body.get("trigger", "")
    try:
        trigger = Trigger(trigger_name)
    except ValueError:
        return web.json_response({"error": f"Unknown trigger: {trigger_name}"}, status=400)
    try:
        prev = machine.state
        new_state = await machine.fire(trigger)
        transition_log.append({"prev": prev.value, "next": new_state.value, "trigger": trigger_name})
        on_transition(prev.value, trigger_name, new_state.value)
        return web.json_response({
            "state": new_state.value, "prev": prev.value, "trigger": trigger_name,
            "available_triggers": [t.value for t in machine.available_triggers()],
            "error_context": machine.error_context,
        })
    except InvalidTransitionError as e:
        return web.json_response({"error": str(e)}, status=400)

async def handle_reset(request):
    global machine, current_session_id, photo_counter
    machine = BoothStateMachine()
    transition_log.clear()
    current_session_id = None
    photo_counter = 0
    init_db()
    return web.json_response(machine.to_dict())


# ── API: Database viewer ────────────────────────────────────────────
async def handle_db_data(request):
    """Return all rows from all tables."""
    tables = {}
    with db.session_scope() as s:
        # Sessions
        rows = s.query(DBSession).all()
        tables["sessions"] = [{
            "id": r.id[:8] + "…",
            "event_name": r.event_name,
            "status": r.status,
            "photo_count": r.photo_count,
            "photos_target": r.photos_target,
            "layout_id": r.layout_id,
            "design_id": r.design_id,
            "composite_path": r.composite_path[:30] + "…" if r.composite_path else None,
            "download_token": r.download_token,
            "created_at": r.created_at[:19] if r.created_at else None,
        } for r in rows]

        # Payments
        rows = s.query(Payment).all()
        tables["payments"] = [{
            "id": r.id[:8] + "…",
            "session_id": r.session_id[:8] + "…",
            "method": r.method,
            "amount_target": r.amount_target,
            "amount_received": r.amount_received,
            "status": r.status,
            "transaction_ref": r.transaction_ref,
        } for r in rows]

        # Media
        rows = s.query(Media).all()
        tables["media"] = [{
            "id": r.id[:8] + "…",
            "session_id": r.session_id[:8] + "…",
            "photo_index": r.photo_index,
            "slot_index": r.slot_index,
            "file_path": r.file_path.split("/")[-1] if r.file_path else None,
            "filter_id": r.filter_id,
            "is_retake": r.is_retake,
            "width": r.width,
            "height": r.height,
        } for r in rows]

        # FrameConfigs
        rows = s.query(FrameConfig).all()
        tables["frame_configs"] = [{
            "id": r.id[:8] + "…",
            "session_id": r.session_id[:8] + "…",
            "layout_id": r.layout_id,
            "design_id": r.design_id,
            "photo_order_json": r.photo_order_json,
            "custom_text": r.custom_text,
        } for r in rows]

        # SyncJobs
        rows = s.query(SyncJob).all()
        tables["sync_queue"] = [{
            "id": r.id[:8] + "…",
            "session_id": (r.session_id[:8] + "…") if r.session_id else None,
            "media_id": (r.media_id[:8] + "…") if r.media_id else None,
            "job_type": r.job_type,
            "status": r.status,
            "attempts": r.attempts,
        } for r in rows]

    return web.json_response(tables)


async def handle_db_schema(request):
    """Return schema metadata for display."""
    schema = {
        "sessions": ["id", "event_name", "status", "photo_count", "photos_target",
                      "layout_id", "design_id", "composite_path", "download_token", "created_at"],
        "payments": ["id", "session_id", "method", "amount_target", "amount_received",
                     "status", "transaction_ref"],
        "media": ["id", "session_id", "photo_index", "slot_index", "file_path",
                  "filter_id", "is_retake", "width", "height"],
        "frame_configs": ["id", "session_id", "layout_id", "design_id",
                         "photo_order_json", "custom_text"],
        "sync_queue": ["id", "session_id", "media_id", "job_type", "status", "attempts"],
    }
    return web.json_response(schema)


# ── Serve HTML ──────────────────────────────────────────────────────
async def handle_index(request):
    return web.FileResponse(os.path.join(_this_dir, "demo_fsm.html"))


# ── App setup ───────────────────────────────────────────────────────
async def main():
    init_db()
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/status", handle_status)
    app.router.add_post("/api/fire", handle_fire)
    app.router.add_post("/api/reset", handle_reset)
    app.router.add_get("/api/db/data", handle_db_data)
    app.router.add_get("/api/db/schema", handle_db_schema)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8888)
    await site.start()

    print("Photobooth FSM + Database Demo")
    print("  http://localhost:8888")
    print("  Press Ctrl+C to stop\n")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down.")
