"""Movie matching and identity resolution module.

Implements prioritized matching:
TMDB ID -> IMDb ID -> Trakt ID -> Exact normalized title + year -> Fuzzy title + year.
Assigns confidence scores and rejects low confidence (< 0.80) automatic matches.
"""

from dataclasses import dataclass
import re
from difflib import SequenceMatcher
from typing import Optional


@dataclass
class MovieIdentity:
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    trakt_id: Optional[int] = None
    letterboxd_slug: Optional[str] = None
    title: str = ""
    year: Optional[int] = None
    confidence: float = 0.0

    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= 0.80


def normalize_title(title: str) -> str:
    """Normalize a movie title for robust matching.
    
    Strips trailing year '(2022)', extra punctuation, and excessive whitespace.
    """
    if not title:
        return ""
    
    t = title.strip().lower()
    # Strip trailing year in parenthesis, e.g. "The Batman (2022)" -> "The Batman"
    t = re.sub(r"\s*\(\d{4}\)\s*$", "", t)
    # Normalize punctuation and symbols to spaces
    t = re.sub(r"[^\w\s]", " ", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_year_from_title(title: str) -> Optional[int]:
    """Extract embedded year like '(2022)' from title string."""
    m = re.search(r"\((\d{4})\)", title)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def calculate_title_similarity(title_a: str, title_b: str) -> float:
    """Calculate normalized similarity ratio between two titles."""
    norm_a = normalize_title(title_a)
    norm_b = normalize_title(title_b)
    if norm_a == norm_b:
        return 1.0
    return SequenceMatcher(None, norm_a, norm_b).ratio()


def resolve_movie(
    title: str,
    year: Optional[int] = None,
    tmdb_id: Optional[int | str] = None,
    imdb_id: Optional[str] = None,
    trakt_id: Optional[int | str] = None,
    letterboxd_slug: Optional[str] = None,
    known_movies: Optional[list[dict]] = None,
) -> MovieIdentity:
    """Resolve movie identity based on priority hierarchy:
    
    1. TMDB ID (confidence 1.00)
    2. IMDb ID (confidence 1.00)
    3. Trakt ID (confidence 1.00)
    4. Exact normalized title + release year (confidence 0.95)
    5. Fuzzy title + release year (confidence >= 0.80)
    6. Low confidence (< 0.80) -> requires manual review
    """
    clean_tmdb_id: Optional[int] = None
    if tmdb_id is not None:
        try:
            clean_tmdb_id = int(str(tmdb_id).strip())
        except (ValueError, TypeError):
            pass

    clean_imdb_id: Optional[str] = None
    if imdb_id is not None:
        s = str(imdb_id).strip()
        if s:
            # Ensure tt prefix if numbers only
            if s.isdigit():
                clean_imdb_id = f"tt{s}"
            else:
                clean_imdb_id = s

    clean_trakt_id: Optional[int] = None
    if trakt_id is not None:
        try:
            clean_trakt_id = int(str(trakt_id).strip())
        except (ValueError, TypeError):
            pass

    # Extract year from title if not explicitly provided
    resolved_year = year
    if resolved_year is None and title:
        resolved_year = extract_year_from_title(title)

    clean_title = re.sub(r"\s*\(\d{4}\)\s*$", "", title).strip() if title else ""

    # 1. External ID check (direct resolution)
    if clean_tmdb_id or clean_imdb_id or clean_trakt_id or letterboxd_slug:
        return MovieIdentity(
            tmdb_id=clean_tmdb_id,
            imdb_id=clean_imdb_id,
            trakt_id=clean_trakt_id,
            letterboxd_slug=letterboxd_slug,
            title=clean_title,
            year=resolved_year,
            confidence=1.00,
        )

    # If we have a catalog/known movies to match against
    if known_movies:
        best_candidate: Optional[dict] = None
        best_score = 0.0

        for candidate in known_movies:
            # Check external IDs first
            c_tmdb = candidate.get("tmdb_id")
            c_imdb = candidate.get("imdb_id")
            c_trakt = candidate.get("trakt_id")

            if clean_tmdb_id and c_tmdb and int(c_tmdb) == clean_tmdb_id:
                best_candidate = candidate
                best_score = 1.00
                break
            if clean_imdb_id and c_imdb and str(c_imdb).lower() == clean_imdb_id.lower():
                best_candidate = candidate
                best_score = 1.00
                break
            if clean_trakt_id and c_trakt and int(c_trakt) == clean_trakt_id:
                best_candidate = candidate
                best_score = 1.00
                break

            # Title & Year comparison
            c_title = candidate.get("title", "")
            c_year = candidate.get("release_year") or candidate.get("year")
            
            sim = calculate_title_similarity(clean_title, c_title)
            year_matches = False
            if resolved_year is not None and c_year is not None:
                year_matches = (abs(int(resolved_year) - int(c_year)) <= 0)
                year_diff = abs(int(resolved_year) - int(c_year))
            else:
                year_matches = True
                year_diff = 0

            if sim == 1.0 and year_matches:
                score = 0.95
            elif sim >= 0.85 and year_matches:
                score = 0.85
            elif sim >= 0.80 and year_diff <= 1:
                score = 0.80
            else:
                score = round(sim * 0.7, 2)

            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate and best_score >= 0.80:
            return MovieIdentity(
                tmdb_id=best_candidate.get("tmdb_id"),
                imdb_id=best_candidate.get("imdb_id"),
                trakt_id=best_candidate.get("trakt_id"),
                letterboxd_slug=best_candidate.get("letterboxd_slug") or letterboxd_slug,
                title=best_candidate.get("title", clean_title),
                year=best_candidate.get("release_year") or resolved_year,
                confidence=best_score,
            )
        elif best_candidate:
            return MovieIdentity(
                tmdb_id=best_candidate.get("tmdb_id"),
                imdb_id=best_candidate.get("imdb_id"),
                trakt_id=best_candidate.get("trakt_id"),
                letterboxd_slug=best_candidate.get("letterboxd_slug") or letterboxd_slug,
                title=clean_title,
                year=resolved_year,
                confidence=best_score,
            )

    # Fallback when no IDs and no matches
    confidence = 0.95 if (clean_title and resolved_year) else (0.50 if clean_title else 0.20)
    return MovieIdentity(
        tmdb_id=clean_tmdb_id,
        imdb_id=clean_imdb_id,
        trakt_id=clean_trakt_id,
        letterboxd_slug=letterboxd_slug,
        title=clean_title,
        year=resolved_year,
        confidence=confidence,
    )
