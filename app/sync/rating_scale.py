"""Canonical Rating Scale module.

Enforces the canonical Letterboxd scale (0.5 to 5.0 in 0.5 increments)
and bidirectional conversion between Trakt (1 to 10 integer) and Letterboxd.
"""

from typing import Optional

# Valid canonical ratings (Letterboxd scale)
VALID_CANONICAL_RATINGS = {0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0}
VALID_TRAKT_RATINGS = set(range(1, 11))


def validate_canonical_rating(rating: Optional[float]) -> Optional[float]:
    """Validate that a rating is a valid canonical rating (0.5 - 5.0, step 0.5) or None."""
    if rating is None:
        return None
    
    # Normalize float representation (e.g. 4 -> 4.0)
    rating_val = float(rating)
    if rating_val not in VALID_CANONICAL_RATINGS:
        raise ValueError(
            f"Invalid canonical rating: {rating}. Must be one of {sorted(VALID_CANONICAL_RATINGS)} or None."
        )
    return rating_val


def validate_trakt_rating(rating: Optional[int]) -> Optional[int]:
    """Validate that a rating is a valid Trakt rating (1 - 10 integer) or None."""
    if rating is None:
        return None
    
    if not isinstance(rating, int):
        # If float like 9.0, convert if integer-equivalent
        if isinstance(rating, float) and rating.is_integer():
            rating = int(rating)
        else:
            raise ValueError(f"Trakt rating must be an integer, got: {type(rating).__name__}")
            
    if rating not in VALID_TRAKT_RATINGS:
        raise ValueError(f"Invalid Trakt rating: {rating}. Must be an integer between 1 and 10 or None.")
    return rating


def letterboxd_to_trakt(rating: Optional[float]) -> Optional[int]:
    """Convert a canonical Letterboxd rating (0.5 - 5.0) to a Trakt rating (1 - 10).
    
    4.5 -> 9
    5.0 -> 10
    None -> None
    """
    if rating is None:
        return None
    val = validate_canonical_rating(rating)
    assert val is not None
    return round(val * 2)


def trakt_to_letterboxd(rating: Optional[int]) -> Optional[float]:
    """Convert a Trakt rating (1 - 10) to a canonical Letterboxd rating (0.5 - 5.0).
    
    9 -> 4.5
    10 -> 5.0
    None -> None
    """
    if rating is None:
        return None
    val = validate_trakt_rating(rating)
    assert val is not None
    return val / 2.0


def ratings_are_equivalent(r1: Optional[float], r2: Optional[float], tolerance: float = 1e-4) -> bool:
    """Check if two canonical ratings are equal, treating None appropriately."""
    if r1 is None and r2 is None:
        return True
    if r1 is None or r2 is None:
        return False
    return abs(r1 - r2) < tolerance
