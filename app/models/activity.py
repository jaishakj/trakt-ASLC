"""Provider-neutral canonical movie activity schemas and domain models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class WatchEventItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    provider: str
    provider_event_id: str
    watched_at: datetime
    source_event_id: Optional[str] = None


@dataclass
class NormalizedMovieActivity:
    """Canonical representation of movie activity.
    
    watched is derived from whether at least one valid watch event exists.
    watch_count is strictly derived from len(watch_events) and NEVER persisted as primary truth.
    """
    movie_id: int
    watch_events: list[WatchEventItem] = field(default_factory=list)
    rating: Optional[float] = None
    title: str = ""
    release_year: Optional[int] = None
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    trakt_id: Optional[int] = None
    letterboxd_slug: Optional[str] = None

    @property
    def watched(self) -> bool:
        return len(self.watch_events) > 0

    @property
    def watch_count(self) -> int:
        return len(self.watch_events)

    @property
    def last_watched_at(self) -> Optional[datetime]:
        if not self.watch_events:
            return None
        return max(e.watched_at for e in self.watch_events)
