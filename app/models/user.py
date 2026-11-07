"""User and Integration database models."""

from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    integrations: Mapped[list["Integration"]] = relationship("Integration", back_populates="user", cascade="all, delete-orphan")
    watch_events: Mapped[list["WatchEvent"]] = relationship("WatchEvent", back_populates="user", cascade="all, delete-orphan")
    provider_activities: Mapped[list["ProviderActivity"]] = relationship("ProviderActivity", back_populates="user", cascade="all, delete-orphan")
    sync_events: Mapped[list["SyncEvent"]] = relationship("SyncEvent", back_populates="user", cascade="all, delete-orphan")
    conflicts: Mapped[list["ConflictRecord"]] = relationship("ConflictRecord", back_populates="user", cascade="all, delete-orphan")


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # 'trakt', 'letterboxd'
    
    # Encrypted OAuth tokens (null for Letterboxd in CSV MVP)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Metadata
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="integrations")

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_provider"),
    )
