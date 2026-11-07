"""Letterboxd CSV parsing and exporting service.

Handles:
- Letterboxd account export zips containing diary.csv, ratings.csv, watched.csv
- Individual diary.csv, ratings.csv, or watched.csv files
- Unified CSVs (Title, Year, tmdbID, imdbID, Rating, WatchedDate)
- Generation of Letterboxd-compatible import CSV files for Trakt-originated activity
"""

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Optional, Union

from app.core.exceptions import ImportFormatError
from app.sync.rating_scale import validate_canonical_rating


@dataclass
class ParsedLetterboxdRow:
    title: str
    year: Optional[int] = None
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    letterboxd_slug: Optional[str] = None
    rating: Optional[float] = None
    watched_date: Optional[datetime] = None
    is_rewatch: bool = False
    raw_uri: Optional[str] = None
    line_number: int = 0


def extract_slug_from_uri(uri: str) -> Optional[str]:
    """Extract film slug from Letterboxd URI like https://letterboxd.com/film/fight-club/."""
    if not uri:
        return None
    m = re.search(r"/film/([^/]+)/?", uri)
    if m:
        return m.group(1)
    return None


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string (YYYY-MM-DD or ISO format) to UTC datetime."""
    if not date_str or not date_str.strip():
        return None
    s = date_str.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def parse_rating(rating_val: str) -> Optional[float]:
    """Parse rating string into canonical 0.5 - 5.0 scale."""
    if not rating_val or not str(rating_val).strip():
        return None
    s = str(rating_val).strip()
    
    # Handle star symbols if present: ★ (U+2605) and ½ (U+00BD)
    if "★" in s or "½" in s:
        stars = s.count("★")
        half = 0.5 if "½" in s else 0.0
        val = stars + half
        return validate_canonical_rating(val)

    try:
        val = float(s)
        # If user supplied a 1-10 rating in a 'Rating10' or raw column
        if val > 5.0 and val <= 10.0 and val.is_integer():
            val = val / 2.0
        return validate_canonical_rating(val)
    except (ValueError, TypeError):
        return None


def _find_col(header_map: dict[str, int], *aliases: str) -> Optional[int]:
    """Find index of header using case-insensitive normalized aliases."""
    for alias in aliases:
        norm = alias.lower().replace(" ", "").replace("_", "").replace("-", "")
        if norm in header_map:
            return header_map[norm]
    return None


def parse_csv_content(content_text: str) -> list[ParsedLetterboxdRow]:
    """Parse a single Letterboxd CSV content string."""
    reader = csv.reader(io.StringIO(content_text))
    rows = list(reader)
    if not rows:
        return []

    # Map headers to indices
    raw_headers = rows[0]
    header_map = {
        h.strip().lower().replace(" ", "").replace("_", "").replace("-", ""): idx
        for idx, h in enumerate(raw_headers)
    }

    title_idx = _find_col(header_map, "name", "title", "film")
    year_idx = _find_col(header_map, "year", "releaseyear")
    tmdb_idx = _find_col(header_map, "tmdbid", "tmdb")
    imdb_idx = _find_col(header_map, "imdbid", "imdb")
    uri_idx = _find_col(header_map, "letterboxduri", "uri", "url")
    rating_idx = _find_col(header_map, "rating", "rating10")
    watched_date_idx = _find_col(header_map, "watcheddate", "date", "watchedat")
    rewatch_idx = _find_col(header_map, "rewatch")

    if title_idx is None and tmdb_idx is None and imdb_idx is None:
        raise ImportFormatError("CSV must contain at least Title, tmdbID, or imdbID column")

    parsed_rows: list[ParsedLetterboxdRow] = []

    for line_num, row in enumerate(rows[1:], start=2):
        if not row or not any(field.strip() for field in row):
            continue

        title = row[title_idx].strip() if title_idx is not None and title_idx < len(row) else ""
        
        year = None
        if year_idx is not None and year_idx < len(row) and row[year_idx].strip():
            try:
                year = int(row[year_idx].strip())
            except ValueError:
                pass

        tmdb_id = None
        if tmdb_idx is not None and tmdb_idx < len(row) and row[tmdb_idx].strip():
            try:
                tmdb_id = int(row[tmdb_idx].strip())
            except ValueError:
                pass

        imdb_id = None
        if imdb_idx is not None and imdb_idx < len(row) and row[imdb_idx].strip():
            imdb_id = row[imdb_idx].strip()

        uri = row[uri_idx].strip() if uri_idx is not None and uri_idx < len(row) else None
        slug = extract_slug_from_uri(uri) if uri else None

        rating = None
        if rating_idx is not None and rating_idx < len(row) and row[rating_idx].strip():
            try:
                rating = parse_rating(row[rating_idx].strip())
            except Exception:
                pass

        watched_date = None
        if watched_date_idx is not None and watched_date_idx < len(row) and row[watched_date_idx].strip():
            watched_date = parse_date(row[watched_date_idx].strip())

        is_rewatch = False
        if rewatch_idx is not None and rewatch_idx < len(row) and row[rewatch_idx].strip():
            val = row[rewatch_idx].strip().lower()
            is_rewatch = val in ("yes", "true", "1", "y")

        if not title and not tmdb_id and not imdb_id:
            continue

        parsed_rows.append(
            ParsedLetterboxdRow(
                title=title,
                year=year,
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                letterboxd_slug=slug,
                rating=rating,
                watched_date=watched_date,
                is_rewatch=is_rewatch,
                raw_uri=uri,
                line_number=line_num,
            )
        )

    return parsed_rows


def parse_letterboxd_import(file_bytes: bytes, filename: str) -> list[ParsedLetterboxdRow]:
    """Parse Letterboxd upload which may be a .zip export archive or a .csv file."""
    if filename.lower().endswith(".zip") or zipfile.is_zipfile(io.BytesIO(file_bytes)):
        results: list[ParsedLetterboxdRow] = []
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            # Look for diary.csv, ratings.csv, watched.csv in order of detail
            names = z.namelist()
            diary_files = [n for n in names if n.lower().endswith("diary.csv")]
            ratings_files = [n for n in names if n.lower().endswith("ratings.csv")]
            watched_files = [n for n in names if n.lower().endswith("watched.csv")]

            # Process diary first (richest data with individual watch dates and ratings)
            for f in diary_files:
                content = z.read(f).decode("utf-8", errors="replace")
                results.extend(parse_csv_content(content))

            # Process ratings
            for f in ratings_files:
                content = z.read(f).decode("utf-8", errors="replace")
                results.extend(parse_csv_content(content))

            # Process watched
            for f in watched_files:
                content = z.read(f).decode("utf-8", errors="replace")
                results.extend(parse_csv_content(content))

        if not results:
            raise ImportFormatError("No diary.csv, ratings.csv, or watched.csv found in the uploaded zip archive")
        return results

    # Direct CSV file
    try:
        content = file_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        raise ImportFormatError(f"Could not decode CSV file as UTF-8: {exc}")

    return parse_csv_content(content)


def generate_letterboxd_export_csv(items: list[dict]) -> str:
    """Generate Letterboxd-compatible CSV export for Trakt-originated changes.
    
    Columns: Title,Year,tmdbID,imdbID,Rating,WatchedDate
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Title", "Year", "tmdbID", "imdbID", "Rating", "WatchedDate"])

    for item in items:
        title = item.get("title", "")
        year = item.get("year") or ""
        tmdb_id = item.get("tmdb_id") or ""
        imdb_id = item.get("imdb_id") or ""
        
        rating = item.get("rating")
        rating_str = f"{rating:.1f}" if rating is not None else ""
        
        watched_date = item.get("watched_date")
        if isinstance(watched_date, datetime):
            w_str = watched_date.strftime("%Y-%m-%d")
        elif isinstance(watched_date, str):
            w_str = watched_date[:10]
        else:
            w_str = ""

        writer.writerow([title, year, tmdb_id, imdb_id, rating_str, w_str])

    return output.getvalue()
