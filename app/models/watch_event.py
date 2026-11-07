"""WatchEvent model for discrete movie viewing events."""

from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WatchEvent(Base):
    __tablename__ = "watch_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)

    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # 'trakt', 'letterboxd'
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    watched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="watch_events")
    movie: Mapped["Movie"] = relationship("Movie", back_populates="watch_events")

    __table_args__ = (
        UniqueConstraint("user_id", "movie_id", "provider", "provider_event_id", name="uq_user_movie_provider_event"),
        Index("ix_watch_event_user_movie", "user_id", "movie_id"),
    )


def derive_event_id(provider: str, movie_id: int, watched_at: datetime) -> str:
    """Derive deterministic event identity when provider does not expose a native stable ID."""
    dt_str = watched_at.strftime("%Y-%m-%d")
    return f"{provider}:{movie_id}:{dt_str}"
