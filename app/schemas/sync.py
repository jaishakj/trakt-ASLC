"""Pydantic schemas for sync requests, responses, and events."""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict


class SyncTriggerRequest(BaseModel):
    user_id: int = 1
    write_to_trakt: bool = True


class DryRunResponse(BaseModel):
    new_watch_events: int
    rating_updates: int
    equivalent_ratings: int
    conflicts: int
    unchanged: int
    unmatched_movies: int
    trakt_movies_count: int
    letterboxd_movies_count: int


class SyncEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    movie_id: int
    source_provider: str
    destination_provider: str
    operation: str
    status: str
    content_hash: str
    idempotency_key: str
    error_message: Optional[str] = None
    created_at: datetime


class ServiceStatusResponse(BaseModel):
    status: str
    trakt_connected: bool
    letterboxd_connected: bool
    last_trakt_sync: Optional[datetime] = None
    last_letterboxd_import: Optional[datetime] = None
    movies_count: int
    watch_events_count: int
    pending_conflicts_count: int
    scheduler_running: bool
    sync_interval_minutes: int
