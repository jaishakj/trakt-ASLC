"""Unit tests for movie identity matching and confidence scoring."""

from app.sync.matcher import (
    MovieIdentity,
    extract_year_from_title,
    normalize_title,
    resolve_movie,
)


def test_matching_title_normalization():
    assert normalize_title("The Batman (2022)") == "the batman"
    assert normalize_title("The Batman") == "the batman"
    assert normalize_title("Fight Club: 10th Anniversary") == "fight club 10th anniversary"


def test_extract_year_from_title():
    assert extract_year_from_title("The Batman (2022)") == 2022
    assert extract_year_from_title("Dune: Part Two (2024)") == 2024
    assert extract_year_from_title("Blade Runner") is None


def test_matching_the_batman_variations():
    """Verify 'The Batman' 2022 and 'The Batman (2022)' resolve consistently."""
    catalog = [
        {
            "tmdb_id": 414906,
            "imdb_id": "tt1877830",
            "trakt_id": 139158,
            "title": "The Batman",
            "release_year": 2022,
        }
    ]

    res1 = resolve_movie("The Batman", year=2022, known_movies=catalog)
    res2 = resolve_movie("The Batman (2022)", known_movies=catalog)

    assert res1.tmdb_id == 414906
    assert res2.tmdb_id == 414906
    assert res1.imdb_id == "tt1877830"
    assert res2.imdb_id == "tt1877830"
    assert res1.confidence >= 0.95
    assert res2.confidence >= 0.95


def test_matching_external_ids_highest_priority():
    """External IDs must grant confidence 1.00 immediately."""
    identity = resolve_movie("Completely Random Title", tmdb_id=550)
    assert identity.tmdb_id == 550
    assert identity.confidence == 1.00

    identity_imdb = resolve_movie("Random Title", imdb_id="tt0137523")
    assert identity_imdb.imdb_id == "tt0137523"
    assert identity_imdb.confidence == 1.00


def test_low_confidence_match_rejection():
    """Low similarity match with no IDs should not have high confidence."""
    catalog = [
        {"title": "Inception", "release_year": 2010, "tmdb_id": 27205}
    ]
    res = resolve_movie("Interstellar", year=2014, known_movies=catalog)
    assert not res.is_high_confidence
    assert res.confidence < 0.80
