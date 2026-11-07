"""Letterboxd Provider implementation using CSV bridge (and future API adapter).

Adheres strictly to the normalized Provider interface.
Consumes parsed CSV data and produces ProviderSnapshot with canonical ratings.
When writes are requested from the sync engine, they are queued for Letterboxd CSV export.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Integration
from app.providers.base import (
    Provider,
    ProviderMovieItem,
    ProviderRating,
    ProviderSnapshot,
    ProviderWatchEvent,
)
from app.services.csv import ParsedLetterboxdRow, generate_letterboxd_export_csv


class LetterboxdProvider(Provider):
    def __init__(self, db_session: Optional[AsyncSession] = None):
        self.db = db_session
        self.pending_export_items: list[dict] = []

    @property
    def provider_name(self) -> str:
        return "letterboxd"

    async def is_connected(self, user_id: int) -> bool:
        """Check if Letterboxd CSV data has been connected/imported for this user."""
        if not self.db:
            return False
        stmt = select(Integration).where(
            Integration.user_id == user_id,
            Integration.provider == "letterboxd",
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none() is not None

    def build_snapshot_from_rows(self, rows: list[ParsedLetterboxdRow]) -> ProviderSnapshot:
        """Construct a normalized ProviderSnapshot from parsed Letterboxd CSV rows."""
        now = datetime.now(timezone.utc)
        watched_movies: dict[str, ProviderMovieItem] = {}
        watch_events: list[ProviderWatchEvent] = []
        ratings: dict[str, ProviderRating] = {}

        for row in rows:
            # Movie identity key
            key = f"{row.tmdb_id or ''}:{row.imdb_id or ''}:{row.title.lower()}:{row.year or ''}"
            m_item = ProviderMovieItem(
                title=row.title,
                year=row.year,
                tmdb_id=row.tmdb_id,
                imdb_id=row.imdb_id,
                letterboxd_slug=row.letterboxd_slug,
            )
            watched_movies[key] = m_item

            # Watch event
            if row.watched_date:
                # Deterministic event ID for diary row
                date_str = row.watched_date.strftime("%Y-%m-%d")
                ev_id = f"letterboxd:{m_item.tmdb_id or m_item.imdb_id or m_item.title.lower()}:{date_str}"
                watch_events.append(
                    ProviderWatchEvent(
                        provider_movie=m_item,
                        watched_at=row.watched_date,
                        provider_event_id=ev_id,
                    )
                )

            # Rating
            if row.rating is not None:
                ratings[key] = ProviderRating(
                    provider_movie=m_item,
                    rating=row.rating,  # Already in canonical 0.5 - 5.0 scale
                    rated_at=row.watched_date,
                )

        return ProviderSnapshot(
            provider="letterboxd",
            watched_movies=list(watched_movies.values()),
            watch_events=watch_events,
            ratings=list(ratings.values()),
            fetched_at=now,
        )

    async def fetch_snapshot(self, user_id: int) -> ProviderSnapshot:
        """Fetch snapshot from stored provider_activity and watch_events for Letterboxd."""
        from app.models.provider_activity import ProviderActivity
        from app.models.watch_event import WatchEvent
        from app.models.movie import Movie

        now = datetime.now(timezone.utc)
        if not self.db:
            return ProviderSnapshot(
                provider="letterboxd",
                watched_movies=[],
                watch_events=[],
                ratings=[],
                fetched_at=now,
            )

        # Load movies and watch events
        stmt = (
            select(WatchEvent, Movie)
            .join(Movie, WatchEvent.movie_id == Movie.id)
            .where(WatchEvent.user_id == user_id, WatchEvent.provider == "letterboxd")
        )
        res = await self.db.execute(stmt)
        we_rows = res.all()

        watch_events: list[ProviderWatchEvent] = []
        movies_map: dict[int, ProviderMovieItem] = {}

        for we, m in we_rows:
            if m.id not in movies_map:
                movies_map[m.id] = ProviderMovieItem(
                    title=m.title,
                    year=m.release_year,
                    tmdb_id=m.tmdb_id,
                    imdb_id=m.imdb_id,
                    trakt_id=m.trakt_id,
                    letterboxd_slug=m.letterboxd_slug,
                )
            watch_events.append(
                ProviderWatchEvent(
                    provider_movie=movies_map[m.id],
                    watched_at=we.watched_at,
                    provider_event_id=we.provider_event_id,
                )
            )

        # Load ratings from provider_activity
        act_stmt = (
            select(ProviderActivity, Movie)
            .join(Movie, ProviderActivity.movie_id == Movie.id)
            .where(ProviderActivity.user_id == user_id, ProviderActivity.provider == "letterboxd")
        )
        act_res = await self.db.execute(act_stmt)
        ratings: list[ProviderRating] = []

        for act, m in act_res.all():
            if m.id not in movies_map:
                movies_map[m.id] = ProviderMovieItem(
                    title=m.title,
                    year=m.release_year,
                    tmdb_id=m.tmdb_id,
                    imdb_id=m.imdb_id,
                    trakt_id=m.trakt_id,
                    letterboxd_slug=m.letterboxd_slug,
                )
            if act.rating is not None:
                ratings.append(
                    ProviderRating(
                        provider_movie=movies_map[m.id],
                        rating=act.rating,
                        rated_at=act.last_watched_at,
                    )
                )

        return ProviderSnapshot(
            provider="letterboxd",
            watched_movies=list(movies_map.values()),
            watch_events=watch_events,
            ratings=ratings,
            fetched_at=now,
        )

    async def mark_watched(
        self,
        user_id: int,
        movie: ProviderMovieItem,
        watched_at: Optional[datetime] = None,
    ) -> bool:
        """Queue a watch event for Letterboxd CSV export."""
        self.pending_export_items.append({
            "title": movie.title,
            "year": movie.year,
            "tmdb_id": movie.tmdb_id,
            "imdb_id": movie.imdb_id,
            "watched_date": watched_at or datetime.now(timezone.utc),
            "rating": None,
        })
        return True

    async def rate_movie(
        self,
        user_id: int,
        movie: ProviderMovieItem,
        canonical_rating: float,
        rated_at: Optional[datetime] = None,
    ) -> bool:
        """Queue a rating update for Letterboxd CSV export."""
        self.pending_export_items.append({
            "title": movie.title,
            "year": movie.year,
            "tmdb_id": movie.tmdb_id,
            "imdb_id": movie.imdb_id,
            "watched_date": rated_at,
            "rating": canonical_rating,
        })
        return True

    async def remove_rating(self, user_id: int, movie: ProviderMovieItem) -> bool:
        """Letterboxd CSV import doesn't easily unrate via CSV, but we can queue it."""
        return True

    def export_queued_changes(self) -> str:
        """Generate Letterboxd-compatible CSV for pending export items."""
        return generate_letterboxd_export_csv(self.pending_export_items)
