"""SyncEvent and ConflictRecord database models."""

from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SyncEvent(Base):
    __tablename__ = "sync_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)

    source_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    destination_provider: Mapped[str] = mapped_column(String(50), nullable=False)

    # Operations: create_watch, update_watch, create_rating, update_rating, remove_rating
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Statuses: pending, success, failed, skipped, conflict
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")

    old_state: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded string
    new_state: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded string

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="sync_events")
    movie: Mapped["Movie"] = relationship("Movie", back_populates="sync_events")

    __table_args__ = (
        Index("ix_sync_events_user_status", "user_id", "status"),
    )


class ConflictRecord(Base):
    __tablename__ = "conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)

    field: Mapped[str] = mapped_column(String(50), nullable=False)  # 'rating', 'watched'
    trakt_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    letterboxd_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")  # 'pending', 'resolved'
    resolution_choice: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 'trakt', 'letterboxd', 'previous', 'custom'

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="conflicts")
    movie: Mapped["Movie"] = relationship("Movie", back_populates="conflicts")

    __table_args__ = (
        Index("ix_conflicts_user_status", "user_id", "status"),
    )
