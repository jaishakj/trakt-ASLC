"""Unit tests for canonical rating scale conversions."""

import pytest
from app.sync.rating_scale import (
    letterboxd_to_trakt,
    trakt_to_letterboxd,
    validate_canonical_rating,
    validate_trakt_rating,
    ratings_are_equivalent,
)


def test_letterboxd_to_trakt_exact_mappings():
    """Verify official mappings required by Section 34:
    0.5 -> 1
    1.0 -> 2
    2.5 -> 5
    4.0 -> 8
    4.5 -> 9
    5.0 -> 10
    """
    assert letterboxd_to_trakt(0.5) == 1
    assert letterboxd_to_trakt(1.0) == 2
    assert letterboxd_to_trakt(2.5) == 5
    assert letterboxd_to_trakt(4.0) == 8
    assert letterboxd_to_trakt(4.5) == 9
    assert letterboxd_to_trakt(5.0) == 10


def test_trakt_to_letterboxd_exact_mappings():
    """Verify reverse mappings required by Section 34:
    1 -> 0.5
    2 -> 1.0
    5 -> 2.5
    8 -> 4.0
    9 -> 4.5
    10 -> 5.0
    """
    assert trakt_to_letterboxd(1) == 0.5
    assert trakt_to_letterboxd(2) == 1.0
    assert trakt_to_letterboxd(5) == 2.5
    assert trakt_to_letterboxd(8) == 4.0
    assert trakt_to_letterboxd(9) == 4.5
    assert trakt_to_letterboxd(10) == 5.0


def test_null_handling():
    """Verify None/null is handled explicitly without errors."""
    assert letterboxd_to_trakt(None) is None
    assert trakt_to_letterboxd(None) is None
    assert validate_canonical_rating(None) is None
    assert validate_trakt_rating(None) is None


def test_invalid_ratings_rejection():
    """Invalid rating values outside defined scales must raise ValueError."""
    with pytest.raises(ValueError):
        validate_canonical_rating(0.3)  # Not 0.5 increment
    with pytest.raises(ValueError):
        validate_canonical_rating(5.5)  # Out of range
    with pytest.raises(ValueError):
        validate_canonical_rating(-1.0)

    with pytest.raises(ValueError):
        validate_trakt_rating(0)  # Trakt scale is 1-10
    with pytest.raises(ValueError):
        validate_trakt_rating(11)
    with pytest.raises(ValueError):
        validate_trakt_rating("invalid")  # Non-integer


def test_ratings_equivalence():
    """Ratings equivalence check with floating point tolerance."""
    assert ratings_are_equivalent(4.5, 4.5)
    assert ratings_are_equivalent(None, None)
    assert not ratings_are_equivalent(4.5, None)
    assert not ratings_are_equivalent(None, 4.0)
    assert not ratings_are_equivalent(4.0, 4.5)
