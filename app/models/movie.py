"""Movie and MovieMapping database models."""

from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Movie(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # External Identifiers
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    imdb_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    trakt_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    letterboxd_slug: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    release_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    mappings: Mapped[list["MovieMapping"]] = relationship("MovieMapping", back_populates="movie", cascade="all, delete-orphan")
    watch_events: Mapped[list["WatchEvent"]] = relationship("WatchEvent", back_populates="movie", cascade="all, delete-orphan")
    provider_activities: Mapped[list["ProviderActivity"]] = relationship("ProviderActivity", back_populates="movie", cascade="all, delete-orphan")
    sync_events: Mapped[list["SyncEvent"]] = relationship("SyncEvent", back_populates="movie", cascade="all, delete-orphan")
    conflicts: Mapped[list["ConflictRecord"]] = relationship("ConflictRecord", back_populates="movie", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_movie_title_year", "title", "release_year"),
    )


class MovieMapping(Base):
    __tablename__ = "movie_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # 'trakt', 'letterboxd', 'tmdb', 'imdb'
    provider_movie_id: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    movie: Mapped["Movie"] = relationship("Movie", back_populates="mappings")

    __table_args__ = (
        Index("ix_mapping_provider_id", "provider", "provider_movie_id"),
    )
