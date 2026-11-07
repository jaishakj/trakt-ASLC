"""ProviderActivity snapshot model representing last known provider state."""

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProviderActivity(Base):
    __tablename__ = "provider_activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)

    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # 'trakt', 'letterboxd'
    provider_movie_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    watched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Stored strictly in canonical Letterboxd scale (0.5 - 5.0) or null
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)

    last_watched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # SHA-256 of semantic state for change detection & loop prevention
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    remote_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="provider_activities")
    movie: Mapped["Movie"] = relationship("Movie", back_populates="provider_activities")

    __table_args__ = (
        UniqueConstraint("user_id", "movie_id", "provider", name="uq_user_movie_provider"),
        Index("ix_provider_activity_lookup", "user_id", "movie_id", "provider"),
    )
