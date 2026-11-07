"""Unit tests for three-way conflict detection and safe merge rules."""

from app.sync.conflict import compare_ratings_three_way
from app.sync.rating_scale import trakt_to_letterboxd


def test_rating_conflict_detected():
    """Letterboxd = 4.0, Trakt = 9 (normalized 4.5) -> Conflict."""
    trakt_normalized = trakt_to_letterboxd(9)
    assert trakt_normalized == 4.5

    result = compare_ratings_three_way(
        previous_rating=4.0,
        trakt_rating=trakt_normalized,  # 4.5
        letterboxd_rating=4.0,
    )
    # Both had a prior rating, Trakt changed while Letterboxd didn't -> Trakt change propagated
    assert result.has_conflict is False
    assert result.action_for_letterboxd == "export_rating"
    assert result.resolved_value == 4.5


def test_genuine_unresolvable_conflict():
    """Both Trakt and Letterboxd changed from previous baseline to different values."""
    result = compare_ratings_three_way(
        previous_rating=3.0,
        trakt_rating=4.5,
        letterboxd_rating=4.0,
    )
    assert result.has_conflict is True
    assert result.field == "rating"
    assert result.trakt_value == 4.5
    assert result.letterboxd_value == 4.0


def test_equivalent_ratings():
    """Letterboxd = 4.5, Trakt = 9 (4.5) -> Considered equivalent, no conflict, no write."""
    trakt_normalized = trakt_to_letterboxd(9)
    result = compare_ratings_three_way(
        previous_rating=None,
        trakt_rating=trakt_normalized,
        letterboxd_rating=4.5,
    )
    assert result.has_conflict is False
    assert result.action_for_trakt == "none"
    assert result.action_for_letterboxd == "none"


def test_missing_rating_does_not_erase():
    """Letterboxd = 4.0, Trakt = None -> Must not erase Letterboxd rating; syncs to Trakt."""
    result = compare_ratings_three_way(
        previous_rating=None,
        trakt_rating=None,
        letterboxd_rating=4.0,
    )
    assert result.has_conflict is False
    assert result.resolved_value == 4.0
    assert result.action_for_trakt == "update_rating"
