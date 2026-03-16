"""SQLAlchemy ORM models for the photobooth local database.

Schema follows PRD §5.2 — five tables:
  sessions, payments, media, frame_configs, sync_queue
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index, UniqueConstraint
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


# ── sessions ────────────────────────────────────────────────────────

class Session(Base):
    """A photobooth session / transaction."""
    __tablename__ = "sessions"

    id                  = Column(String(36), primary_key=True, default=_uuid)
    event_name          = Column(String(255), nullable=True)
    status              = Column(String(20), nullable=False, default="active")
    created_at          = Column(String(30), nullable=False, default=_now)
    completed_at        = Column(String(30), nullable=True)
    photo_count         = Column(Integer, nullable=False, default=0)
    photos_target       = Column(Integer, nullable=False, default=4)
    layout_id           = Column(String(50), nullable=True)
    design_id           = Column(String(50), nullable=True)
    composite_path      = Column(Text, nullable=True)
    download_token      = Column(String(64), nullable=True, unique=True)
    download_expires_at = Column(String(30), nullable=True)
    metadata_json       = Column(Text, nullable=True)

    # Relationships
    media        = relationship("Media", back_populates="session", cascade="all, delete-orphan")
    payment      = relationship("Payment", back_populates="session", uselist=False, cascade="all, delete-orphan")
    frame_config = relationship("FrameConfig", back_populates="session", uselist=False, cascade="all, delete-orphan")
    sync_jobs    = relationship("SyncJob", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Session {self.id[:8]}… status={self.status}>"


# ── payments ────────────────────────────────────────────────────────

class Payment(Base):
    """Payment record for a session (QRIS or cash)."""
    __tablename__ = "payments"

    id              = Column(String(36), primary_key=True, default=_uuid)
    session_id      = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    method          = Column(String(10), nullable=False)          # "qris" or "cash"
    amount_target   = Column(Integer, nullable=False)
    amount_received = Column(Integer, nullable=False, default=0)
    status          = Column(String(20), nullable=False, default="pending")
    transaction_ref = Column(String(255), nullable=True)
    qr_code_data    = Column(Text, nullable=True)
    created_at      = Column(String(30), nullable=False, default=_now)
    confirmed_at    = Column(String(30), nullable=True)
    expires_at      = Column(String(30), nullable=True)
    metadata_json   = Column(Text, nullable=True)

    session = relationship("Session", back_populates="payment")

    __table_args__ = (
        Index("ix_payments_session", "session_id"),
        Index("ix_payments_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Payment {self.id[:8]}… method={self.method} status={self.status}>"


# ── media ───────────────────────────────────────────────────────────

class Media(Base):
    """A photo captured during a session."""
    __tablename__ = "media"

    id              = Column(String(36), primary_key=True, default=_uuid)
    session_id      = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    photo_index     = Column(Integer, nullable=False)
    slot_index      = Column(Integer, nullable=True)
    file_path       = Column(Text, nullable=False)
    thumbnail_path  = Column(Text, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    width           = Column(Integer, nullable=True)
    height          = Column(Integer, nullable=True)
    filter_id       = Column(String(30), nullable=True, default="original")
    is_retake       = Column(Integer, nullable=False, default=0)
    retake_of       = Column(String(36), ForeignKey("media.id"), nullable=True)
    retake_count    = Column(Integer, nullable=False, default=0)
    captured_at     = Column(String(30), nullable=False, default=_now)
    printed         = Column(Integer, nullable=False, default=0)
    metadata_json   = Column(Text, nullable=True)

    session   = relationship("Session", back_populates="media")
    sync_jobs = relationship("SyncJob", back_populates="media", cascade="all, delete-orphan")
    original  = relationship("Media", remote_side="Media.id", uselist=False)

    __table_args__ = (
        Index("ix_media_session", "session_id"),
    )

    def __repr__(self) -> str:
        return f"<Media {self.id[:8]}… session={self.session_id[:8]}… idx={self.photo_index}>"


# ── frame_configs ───────────────────────────────────────────────────

class FrameConfig(Base):
    """Frame layout & design configuration for a session."""
    __tablename__ = "frame_configs"

    id               = Column(String(36), primary_key=True, default=_uuid)
    session_id       = Column(String(36), ForeignKey("sessions.id"), nullable=False, unique=True)
    layout_id        = Column(String(50), nullable=False)
    design_id        = Column(String(50), nullable=False)
    photo_order_json = Column(Text, nullable=False)
    custom_text      = Column(Text, nullable=True)
    created_at       = Column(String(30), nullable=False, default=_now)
    updated_at       = Column(String(30), nullable=False, default=_now)

    session = relationship("Session", back_populates="frame_config")

    def __repr__(self) -> str:
        return f"<FrameConfig {self.id[:8]}… layout={self.layout_id} design={self.design_id}>"


# ── sync_queue ──────────────────────────────────────────────────────

class SyncJob(Base):
    """A job queued for cloud sync (Supabase / S3)."""
    __tablename__ = "sync_queue"

    id              = Column(String(36), primary_key=True, default=_uuid)
    media_id        = Column(String(36), ForeignKey("media.id"), nullable=True)
    session_id      = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    job_type        = Column(String(30), nullable=False)   # upload_photo | upload_composite | upload_session
    status          = Column(String(20), nullable=False, default="pending")
    attempts        = Column(Integer, nullable=False, default=0)
    max_attempts    = Column(Integer, nullable=False, default=5)
    target_url      = Column(Text, nullable=True)
    error_message   = Column(Text, nullable=True)
    created_at      = Column(String(30), nullable=False, default=_now)
    last_attempt_at = Column(String(30), nullable=True)
    completed_at    = Column(String(30), nullable=True)

    media   = relationship("Media", back_populates="sync_jobs")
    session = relationship("Session", back_populates="sync_jobs")

    __table_args__ = (
        Index("ix_sync_status", "status"),
        Index("ix_sync_session", "session_id"),
    )

    def __repr__(self) -> str:
        return f"<SyncJob {self.id[:8]}… type={self.job_type} status={self.status}>"
