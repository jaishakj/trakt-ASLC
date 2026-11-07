"""Unit tests for semantic content hashing stability and sensitivity."""

from datetime import datetime, timezone
from app.sync.hashing import compute_semantic_hash


def test_hash_stability_across_metadata():
    """Bookkeeping metadata (timestamps, IDs) must NOT affect the semantic hash."""
    dates = ["2026-08-01T19:30:00Z", "2026-08-20T21:00:00Z"]

    hash_run_1 = compute_semantic_hash(
        watched=True,
        rating=4.5,
        watch_events=dates,
        last_watched_at="2026-08-20T21:00:00Z",
    )

    # Identical semantic state, event order reversed or passed as datetimes
    dates_reversed = ["2026-08-20T21:00:00Z", "2026-08-01T19:30:00Z"]
    hash_run_2 = compute_semantic_hash(
        watched=True,
        rating=4.5,
        watch_events=dates_reversed,
        last_watched_at="2026-08-20T21:00:00Z",
    )

    assert hash_run_1 == hash_run_2


def test_hash_sensitivity_on_rating_change():
    """Changing rating must change semantic hash."""
    events = ["2026-08-01T19:30:00Z"]
    h1 = compute_semantic_hash(watched=True, rating=4.0, watch_events=events)
    h2 = compute_semantic_hash(watched=True, rating=4.5, watch_events=events)
    assert h1 != h2


def test_hash_sensitivity_on_watch_date_change():
    """Changing watch date must change semantic hash."""
    h1 = compute_semantic_hash(watched=True, rating=4.5, watch_events=["2026-08-01T19:30:00Z"])
    h2 = compute_semantic_hash(watched=True, rating=4.5, watch_events=["2026-08-02T19:30:00Z"])
    assert h1 != h2


def test_hash_sensitivity_on_watched_state_change():
    """Changing watched state must change semantic hash."""
    h1 = compute_semantic_hash(watched=False, rating=None, watch_events=[])
    h2 = compute_semantic_hash(watched=True, rating=None, watch_events=[])
    assert h1 != h2
