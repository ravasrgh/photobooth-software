"""Unit tests for the SQLite database models and session factory."""

import pytest
from sqlalchemy.exc import IntegrityError
from hw_controller.db.models import Session, Media, SyncJob, Payment, FrameConfig


# ── Session ─────────────────────────────────────────────────────────

class TestSessionModel:
    def test_create_session(self, db):
        with db.session_scope() as s:
            session = Session(event_name="Wedding")
            s.add(session)
            s.flush()
            assert session.id is not None
            assert session.status == "active"
            assert session.photo_count == 0

    def test_session_defaults(self, db):
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()
            assert len(session.id) == 36  # UUID v4
            assert session.created_at is not None
            assert session.photos_target == 4
            assert session.layout_id is None
            assert session.design_id is None
            assert session.composite_path is None
            assert session.download_token is None
            assert session.download_expires_at is None

    def test_extended_session_fields(self, db):
        with db.session_scope() as s:
            session = Session(
                photos_target=6,
                layout_id="strip_2x3",
                design_id="retro_kawaii",
                composite_path="/data/sessions/abc/composite.jpg",
                download_token="tok_abc123xyz",
                download_expires_at="2026-03-16T20:00:00Z",
            )
            s.add(session)
            s.flush()
            assert session.photos_target == 6
            assert session.layout_id == "strip_2x3"
            assert session.design_id == "retro_kawaii"
            assert session.composite_path == "/data/sessions/abc/composite.jpg"
            assert session.download_token == "tok_abc123xyz"

    def test_download_token_unique(self, db):
        """download_token must be unique across sessions."""
        with db.session_scope() as s:
            s.add(Session(download_token="unique_tok_1"))
            s.flush()

        with pytest.raises(IntegrityError):
            with db.session_scope() as s:
                s.add(Session(download_token="unique_tok_1"))
                s.flush()

    def test_list_sessions(self, db):
        with db.session_scope() as s:
            s.add(Session(event_name="Party"))
            s.add(Session(event_name="Corporate"))

        with db.session_scope() as s:
            sessions = s.query(Session).all()
            assert len(sessions) == 2


# ── Payment ─────────────────────────────────────────────────────────

class TestPaymentModel:
    def test_create_payment(self, db):
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            payment = Payment(
                session_id=session.id,
                method="qris",
                amount_target=50000,
            )
            s.add(payment)
            s.flush()
            assert payment.id is not None
            assert payment.status == "pending"
            assert payment.amount_received == 0
            assert payment.created_at is not None

    def test_payment_defaults(self, db):
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            payment = Payment(
                session_id=session.id,
                method="cash",
                amount_target=50000,
            )
            s.add(payment)
            s.flush()
            assert payment.transaction_ref is None
            assert payment.qr_code_data is None
            assert payment.confirmed_at is None
            assert payment.expires_at is None

    def test_payment_full_fields(self, db):
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            payment = Payment(
                session_id=session.id,
                method="qris",
                amount_target=50000,
                amount_received=50000,
                status="confirmed",
                transaction_ref="TXN-12345",
                qr_code_data="00020101021126...",
                confirmed_at="2026-03-16T19:00:00Z",
                expires_at="2026-03-16T19:05:00Z",
                metadata_json='{"gateway_response": "ok"}',
            )
            s.add(payment)
            s.flush()
            assert payment.amount_received == 50000
            assert payment.transaction_ref == "TXN-12345"

    def test_session_payment_relationship(self, db):
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            payment = Payment(
                session_id=session.id,
                method="qris",
                amount_target=50000,
            )
            s.add(payment)
            s.flush()

            assert session.payment is not None
            assert session.payment.id == payment.id

    def test_cascade_delete_payment(self, db):
        """Deleting a session should delete its payment."""
        sess_id = None
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()
            sess_id = session.id

            s.add(Payment(session_id=sess_id, method="cash", amount_target=50000))
            s.flush()

        with db.session_scope() as s:
            session = s.query(Session).get(sess_id)
            s.delete(session)

        with db.session_scope() as s:
            assert s.query(Payment).count() == 0

    def test_payment_requires_session(self, db):
        """Payment must reference an existing session."""
        with pytest.raises(IntegrityError):
            with db.session_scope() as s:
                s.add(Payment(
                    session_id="nonexistent-id",
                    method="qris",
                    amount_target=50000,
                ))
                s.flush()


# ── FrameConfig ─────────────────────────────────────────────────────

class TestFrameConfigModel:
    def test_create_frame_config(self, db):
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            fc = FrameConfig(
                session_id=session.id,
                layout_id="strip_2x2",
                design_id="retro_kawaii",
                photo_order_json="[1, 2, 3, 4]",
            )
            s.add(fc)
            s.flush()
            assert fc.id is not None
            assert fc.created_at is not None
            assert fc.updated_at is not None
            assert fc.custom_text is None

    def test_frame_config_custom_text(self, db):
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            fc = FrameConfig(
                session_id=session.id,
                layout_id="single",
                design_id="minimal",
                photo_order_json="[1]",
                custom_text="Happy Birthday!",
            )
            s.add(fc)
            s.flush()
            assert fc.custom_text == "Happy Birthday!"

    def test_session_frame_config_relationship(self, db):
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            fc = FrameConfig(
                session_id=session.id,
                layout_id="grid_2x2",
                design_id="pastel",
                photo_order_json="[1, 2, 3, 4]",
            )
            s.add(fc)
            s.flush()

            assert session.frame_config is not None
            assert session.frame_config.layout_id == "grid_2x2"

    def test_unique_session_constraint(self, db):
        """Only one FrameConfig per session."""
        sess_id = None
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()
            sess_id = session.id

            s.add(FrameConfig(
                session_id=sess_id,
                layout_id="strip",
                design_id="theme_a",
                photo_order_json="[1, 2]",
            ))
            s.flush()

        with pytest.raises(IntegrityError):
            with db.session_scope() as s:
                s.add(FrameConfig(
                    session_id=sess_id,
                    layout_id="grid",
                    design_id="theme_b",
                    photo_order_json="[1, 2]",
                ))
                s.flush()

    def test_cascade_delete_frame_config(self, db):
        """Deleting a session should delete its frame_config."""
        sess_id = None
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()
            sess_id = session.id

            s.add(FrameConfig(
                session_id=sess_id,
                layout_id="strip",
                design_id="default",
                photo_order_json="[1]",
            ))
            s.flush()

        with db.session_scope() as s:
            session = s.query(Session).get(sess_id)
            s.delete(session)

        with db.session_scope() as s:
            assert s.query(FrameConfig).count() == 0


# ── Media ───────────────────────────────────────────────────────────

class TestMediaModel:
    def test_create_media(self, db):
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            media = Media(
                session_id=session.id,
                photo_index=1,
                file_path="/data/sessions/test/photo_001.jpg",
                width=6000,
                height=4000,
                file_size_bytes=5_000_000,
            )
            s.add(media)
            s.flush()
            assert media.id is not None
            assert media.printed == 0

    def test_media_new_defaults(self, db):
        """Verify new column defaults (filter_id, is_retake, retake_count)."""
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            media = Media(
                session_id=session.id,
                photo_index=1,
                file_path="/test.jpg",
            )
            s.add(media)
            s.flush()
            assert media.filter_id == "original"
            assert media.is_retake == 0
            assert media.retake_of is None
            assert media.retake_count == 0
            assert media.slot_index is None

    def test_media_slot_and_filter(self, db):
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            media = Media(
                session_id=session.id,
                photo_index=1,
                slot_index=2,
                file_path="/photo.jpg",
                filter_id="vintage",
            )
            s.add(media)
            s.flush()
            assert media.slot_index == 2
            assert media.filter_id == "vintage"

    def test_media_retake_fields(self, db):
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            original = Media(
                session_id=session.id,
                photo_index=1,
                file_path="/original.jpg",
            )
            s.add(original)
            s.flush()

            retake = Media(
                session_id=session.id,
                photo_index=2,
                file_path="/retake.jpg",
                is_retake=1,
                retake_of=original.id,
                retake_count=1,
            )
            s.add(retake)
            s.flush()
            assert retake.is_retake == 1
            assert retake.retake_of == original.id
            assert retake.retake_count == 1

    def test_session_media_relationship(self, db):
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            for i in range(3):
                s.add(Media(
                    session_id=session.id,
                    photo_index=i + 1,
                    file_path=f"/data/test/photo_{i+1:03d}.jpg",
                ))
            s.flush()
            assert len(session.media) == 3

    def test_cascade_delete(self, db):
        """Deleting a session should delete its media."""
        sess_id = None
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()
            sess_id = session.id

            s.add(Media(session_id=sess_id, photo_index=1, file_path="/x.jpg"))
            s.flush()

        with db.session_scope() as s:
            session = s.query(Session).get(sess_id)
            s.delete(session)

        with db.session_scope() as s:
            assert s.query(Media).count() == 0


# ── SyncJob ─────────────────────────────────────────────────────────

class TestSyncJobModel:
    def test_create_sync_job(self, db):
        with db.session_scope() as s:
            job = SyncJob(job_type="upload_session", status="pending")
            s.add(job)
            s.flush()
            assert job.id is not None
            assert job.attempts == 0
            assert job.max_attempts == 5

    def test_sync_job_linked_to_media(self, db):
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            media = Media(
                session_id=session.id,
                photo_index=1,
                file_path="/test.jpg",
            )
            s.add(media)
            s.flush()

            job = SyncJob(
                media_id=media.id,
                job_type="upload_photo",
                status="pending",
            )
            s.add(job)
            s.flush()
            assert job.media_id == media.id
            assert len(media.sync_jobs) == 1

    def test_sync_job_linked_to_session(self, db):
        """SyncJob can reference a session directly (e.g. upload_composite)."""
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()

            job = SyncJob(
                session_id=session.id,
                job_type="upload_composite",
                status="pending",
            )
            s.add(job)
            s.flush()
            assert job.session_id == session.id
            assert len(session.sync_jobs) == 1

    def test_query_pending_jobs(self, db):
        with db.session_scope() as s:
            s.add(SyncJob(job_type="upload_session", status="pending"))
            s.add(SyncJob(job_type="upload_photo", status="completed"))
            s.add(SyncJob(job_type="upload_photo", status="pending"))

        with db.session_scope() as s:
            pending = s.query(SyncJob).filter_by(status="pending").all()
            assert len(pending) == 2

    def test_cascade_delete_session_sync_jobs(self, db):
        """Deleting a session should delete its sync jobs."""
        sess_id = None
        with db.session_scope() as s:
            session = Session()
            s.add(session)
            s.flush()
            sess_id = session.id

            s.add(SyncJob(session_id=sess_id, job_type="upload_composite", status="pending"))
            s.flush()

        with db.session_scope() as s:
            session = s.query(Session).get(sess_id)
            s.delete(session)

        with db.session_scope() as s:
            assert s.query(SyncJob).count() == 0


# ── Database Session Scope ──────────────────────────────────────────

class TestDatabaseSessionScope:
    def test_rollback_on_error(self, db):
        """Verify that errors trigger a rollback."""
        try:
            with db.session_scope() as s:
                s.add(Session(event_name="Should rollback"))
                raise ValueError("Intentional error")
        except ValueError:
            pass

        with db.session_scope() as s:
            assert s.query(Session).count() == 0
