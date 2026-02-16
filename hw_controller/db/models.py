"""SQLAlchemy ORM models for the photobooth local database."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Declarative base for all models."""
    pass


def _uuid() -> str:
    """Generate a new UUID v4 string."""
    return str(uuid.uuid4())


def _now() -> str:
    """Current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class Session(Base):
    """A photobooth session / transaction."""
    __tablename__ = "sessions"

    id            = Column(String(36), primary_key=True, default=_uuid)
    event_name    = Column(String(255), nullable=True)
    status        = Column(String(20), nullable=False, default="active")
    created_at    = Column(String(30), nullable=False, default=_now)
    completed_at  = Column(String(30), nullable=True)
    photo_count   = Column(Integer, nullable=False, default=0)
    metadata_json = Column(Text, nullable=True)

    media = relationship("Media", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Session {self.id[:8]}… status={self.status}>"


class Media(Base):
    """A photo captured during a session."""
    __tablename__ = "media"

    id              = Column(String(36), primary_key=True, default=_uuid)
    session_id      = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    photo_index     = Column(Integer, nullable=False)
    file_path       = Column(Text, nullable=False)
    thumbnail_path  = Column(Text, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    width           = Column(Integer, nullable=True)
    height          = Column(Integer, nullable=True)
    captured_at     = Column(String(30), nullable=False, default=_now)
    printed         = Column(Integer, nullable=False, default=0)
    metadata_json   = Column(Text, nullable=True)

    session   = relationship("Session", back_populates="media")
    sync_jobs = relationship("SyncJob", back_populates="media", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_media_session", "session_id"),
    )

    def __repr__(self) -> str:
        return f"<Media {self.id[:8]}… session={self.session_id[:8]}… idx={self.photo_index}>"


class SyncJob(Base):
    """A job queued for cloud sync (Supabase / S3)."""
    __tablename__ = "sync_queue"

    id              = Column(String(36), primary_key=True, default=_uuid)
    media_id        = Column(String(36), ForeignKey("media.id"), nullable=True)
    job_type        = Column(String(30), nullable=False)   # upload_photo | upload_session
    status          = Column(String(20), nullable=False, default="pending")
    attempts        = Column(Integer, nullable=False, default=0)
    max_attempts    = Column(Integer, nullable=False, default=5)
    target_url      = Column(Text, nullable=True)
    error_message   = Column(Text, nullable=True)
    created_at      = Column(String(30), nullable=False, default=_now)
    last_attempt_at = Column(String(30), nullable=True)
    completed_at    = Column(String(30), nullable=True)

    media = relationship("Media", back_populates="sync_jobs")

    __table_args__ = (
        Index("ix_sync_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<SyncJob {self.id[:8]}… type={self.job_type} status={self.status}>"
