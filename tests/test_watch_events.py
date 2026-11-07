"""Unit tests for discrete watch events model and event aggregation."""

from datetime import datetime, timezone
from app.models.activity import NormalizedMovieActivity, WatchEventItem
from app.models.movie import Movie
from app.models.watch_event import WatchEvent, derive_event_id
from app.sync.normalizer import build_canonical_activity


def test_discrete_watch_events_multiple_viewings():
    """Verify Section 34 test requirement:
    Dune viewed on 2026-01-01, 2026-02-01, 2026-03-01
    produces 3 watch events, watch_count = 3, without storing watch_count as authoritative data.
    """
    movie = Movie(id=1, title="Dune", release_year=2021, tmdb_id=438631)
    
    dates = [
        datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc),
        datetime(2026, 2, 1, 21, 30, tzinfo=timezone.utc),
        datetime(2026, 3, 1, 19, 0, tzinfo=timezone.utc),
    ]

    events = [
        WatchEvent(
            id=idx,
            user_id=1,
            movie_id=movie.id,
            provider="letterboxd",
            provider_event_id=f"lb_ev_{idx}",
            watched_at=dt,
        )
        for idx, dt in enumerate(dates, start=1)
    ]

    canonical = build_canonical_activity(movie, events, canonical_rating=4.5)

    assert canonical.watched is True
    assert canonical.watch_count == 3
    assert len(canonical.watch_events) == 3
    assert canonical.last_watched_at == datetime(2026, 3, 1, 19, 0, tzinfo=timezone.utc)
    # Ensure watch_count is a dynamic property, not a static attribute
    assert hasattr(NormalizedMovieActivity, "watch_count")
    assert isinstance(getattr(NormalizedMovieActivity, "watch_count"), property)


def test_derive_event_id_deterministic():
    """Deterministic event id derivation from provider, movie_id, watched_at."""
    dt = datetime(2026, 5, 10, 14, 0, tzinfo=timezone.utc)
    id1 = derive_event_id("trakt", 42, dt)
    id2 = derive_event_id("trakt", 42, dt)
    assert id1 == id2
    assert id1 == "trakt:42:2026-05-10"
