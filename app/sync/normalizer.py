"""Canonical activity normalizer.

Builds NormalizedMovieActivity domain objects from database entities or provider snapshots.
Ensures watch_count is derived dynamically from len(watch_events), watched is derived from
existence of valid events, and ratings conform to the canonical scale.
"""

from typing import Iterable, Optional
from app.models.activity import NormalizedMovieActivity, WatchEventItem
from app.models.movie import Movie
from app.models.watch_event import WatchEvent
from app.sync.rating_scale import validate_canonical_rating


def build_canonical_activity(
    movie: Movie,
    watch_events: Iterable[WatchEvent],
    canonical_rating: Optional[float] = None,
) -> NormalizedMovieActivity:
    """Construct NormalizedMovieActivity from movie and associated watch events."""
    items: list[WatchEventItem] = []
    for we in watch_events:
        items.append(
            WatchEventItem(
                id=we.id,
                provider=we.provider,
                provider_event_id=we.provider_event_id,
                watched_at=we.watched_at,
                source_event_id=we.source_event_id,
            )
        )

    # Sort watch events chronologically
    items.sort(key=lambda x: x.watched_at)

    clean_rating = validate_canonical_rating(canonical_rating) if canonical_rating is not None else None

    return NormalizedMovieActivity(
        movie_id=movie.id,
        watch_events=items,
        rating=clean_rating,
        title=movie.title,
        release_year=movie.release_year,
        tmdb_id=movie.tmdb_id,
        imdb_id=movie.imdb_id,
        trakt_id=movie.trakt_id,
        letterboxd_slug=movie.letterboxd_slug,
    )
