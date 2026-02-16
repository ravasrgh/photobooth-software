"""Unit tests for the SQLite database models and session factory."""

import pytest
from hw_controller.db.models import Session, Media, SyncJob


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

    def test_list_sessions(self, db):
        with db.session_scope() as s:
            s.add(Session(event_name="Party"))
            s.add(Session(event_name="Corporate"))

        with db.session_scope() as s:
            sessions = s.query(Session).all()
            assert len(sessions) == 2


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

    def test_query_pending_jobs(self, db):
        with db.session_scope() as s:
            s.add(SyncJob(job_type="upload_session", status="pending"))
            s.add(SyncJob(job_type="upload_photo", status="completed"))
            s.add(SyncJob(job_type="upload_photo", status="pending"))

        with db.session_scope() as s:
            pending = s.query(SyncJob).filter_by(status="pending").all()
            assert len(pending) == 2


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
