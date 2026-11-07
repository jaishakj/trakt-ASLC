"""Pydantic schemas for activity and movie responses."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class WatchEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    movie_id: int
    movie_title: Optional[str] = None
    release_year: Optional[int] = None
    provider: str
    provider_event_id: str
    watched_at: datetime
    created_at: datetime


class MovieSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    release_year: Optional[int] = None
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    trakt_id: Optional[int] = None
    letterboxd_slug: Optional[str] = None
    canonical_rating: Optional[float] = None
    watch_count: int = 0
    last_watched_at: Optional[datetime] = None
