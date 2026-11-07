"""Trakt API v2 Provider implementation.

Handles OAuth2, token refresh, exponential backoff, rate limiting, and all read/write sync operations.
Converts ratings between Trakt (1-10) and Canonical Letterboxd (0.5-5.0).
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from app.models.user import Integration, User
from app.providers.base import (
    Provider,
    ProviderMovieItem,
    ProviderRating,
    ProviderSnapshot,
    ProviderWatchEvent,
)
from app.services.encryption import decrypt_token, encrypt_token
from app.sync.rating_scale import letterboxd_to_trakt, trakt_to_letterboxd

logger = logging.getLogger(__name__)

TRAKT_API_BASE = "https://api.trakt.tv"


class TraktProvider(Provider):
    def __init__(self, db_session: Optional[AsyncSession] = None):
        self.db = db_session
        self.client_id = settings.TRAKT_CLIENT_ID
        self.client_secret = settings.TRAKT_CLIENT_SECRET
        self.redirect_uri = settings.TRAKT_REDIRECT_URI

    @property
    def provider_name(self) -> str:
        return "trakt"

    def get_authorization_url(self, state: str) -> str:
        """Build Trakt OAuth authorization URL."""
        return (
            f"https://trakt.tv/oauth/authorize?response_type=code"
            f"&client_id={self.client_id}&redirect_uri={self.redirect_uri}&state={state}"
        )

    async def exchange_code_for_token(self, code: str) -> dict:
        """Exchange OAuth authorization code for access and refresh tokens."""
        url = f"{TRAKT_API_BASE}/oauth/token"
        payload = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                raise ProviderAuthError(f"Trakt OAuth token exchange failed: {resp.text}")
            return resp.json()

    async def refresh_access_token(self, integration: Integration) -> str:
        """Refresh expired Trakt access token."""
        raw_refresh = decrypt_token(integration.refresh_token)
        if not raw_refresh:
            raise ProviderAuthError("No refresh token available to refresh Trakt integration")

        url = f"{TRAKT_API_BASE}/oauth/token"
        payload = {
            "refresh_token": raw_refresh,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                raise ProviderAuthError(f"Trakt token refresh failed: {resp.text}")
            
            data = resp.json()
            new_access = data.get("access_token")
            new_refresh = data.get("refresh_token")
            expires_in = data.get("expires_in", 7776000)

            integration.access_token = encrypt_token(new_access)
            if new_refresh:
                integration.refresh_token = encrypt_token(new_refresh)
            integration.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            integration.updated_at = datetime.now(timezone.utc)
            if self.db:
                await self.db.commit()
            return new_access

    async def get_valid_access_token(self, user_id: int) -> str:
        """Retrieve valid decrypted access token, automatically refreshing if expired."""
        if not self.db:
            raise ProviderAuthError("Database session required to load Trakt credentials")

        stmt = select(Integration).where(
            Integration.user_id == user_id,
            Integration.provider == "trakt"
        )
        res = await self.db.execute(stmt)
        integration = res.scalar_one_or_none()

        if not integration or not integration.access_token:
            raise ProviderAuthError("Trakt is not connected for this user")

        # Check expiration
        now = datetime.now(timezone.utc)
        if integration.token_expires_at and integration.token_expires_at <= now + timedelta(minutes=5):
            return await self.refresh_access_token(integration)

        token = decrypt_token(integration.access_token)
        if not token:
            raise ProviderAuthError("Failed to decrypt stored Trakt access token")
        return token

    async def _request(
        self,
        method: str,
        endpoint: str,
        user_id: int,
        json_data: Optional[Any] = None,
        params: Optional[dict] = None,
        max_retries: int = 3,
    ) -> Any:
        """Execute authenticated Trakt API request with rate-limit handling and backoff."""
        token = await self.get_valid_access_token(user_id)
        url = f"{TRAKT_API_BASE}/{endpoint.lstrip('/')}"
        headers = {
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": self.client_id,
            "Authorization": f"Bearer {token}",
        }

        delay = 1.0
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.request(method, url, headers=headers, json=json_data, params=params)
                    
                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("Retry-After", str(int(delay))))
                        logger.warning(f"Trakt rate limit encountered (429). Retrying after {retry_after}s.")
                        if attempt == max_retries - 1:
                            raise ProviderRateLimitError(retry_after=retry_after)
                        await asyncio.sleep(retry_after)
                        continue

                    if resp.status_code == 401:
                        # Attempt single token refresh on 401
                        if attempt == 0 and self.db:
                            stmt = select(Integration).where(Integration.user_id == user_id, Integration.provider == "trakt")
                            res = await self.db.execute(stmt)
                            integration = res.scalar_one_or_none()
                            if integration:
                                token = await self.refresh_access_token(integration)
                                headers["Authorization"] = f"Bearer {token}"
                                continue
                        raise ProviderAuthError(f"Trakt authorization rejected: {resp.text}")

                    if resp.status_code in (500, 502, 503, 504):
                        if attempt == max_retries - 1:
                            raise ProviderUnavailableError(f"Trakt server error {resp.status_code}: {resp.text}")
                        await asyncio.sleep(delay)
                        delay *= 2
                        continue

                    if resp.status_code >= 400:
                        raise ProviderUnavailableError(f"Trakt API error {resp.status_code}: {resp.text}")

                    if resp.status_code == 204:
                        return None
                    return resp.json()

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == max_retries - 1:
                    raise ProviderUnavailableError(f"Trakt network connection error: {exc}")
                await asyncio.sleep(delay)
                delay *= 2

    async def is_connected(self, user_id: int) -> bool:
        if not self.db:
            return False
        stmt = select(Integration).where(
            Integration.user_id == user_id,
            Integration.provider == "trakt",
            Integration.access_token.isnot(None),
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none() is not None

    async def fetch_snapshot(self, user_id: int) -> ProviderSnapshot:
        """Fetch Trakt watched movies, discrete history play events, and ratings."""
        now = datetime.now(timezone.utc)

        # 1. Fetch watched movies summary
        watched_data = await self._request("GET", "/sync/watched/movies?extended=full", user_id)
        watched_movies: list[ProviderMovieItem] = []
        if isinstance(watched_data, list):
            for item in watched_data:
                m_info = item.get("movie", {})
                ids = m_info.get("ids", {})
                watched_movies.append(
                    ProviderMovieItem(
                        title=m_info.get("title", ""),
                        year=m_info.get("year"),
                        tmdb_id=ids.get("tmdb"),
                        imdb_id=ids.get("imdb"),
                        trakt_id=ids.get("trakt"),
                        letterboxd_slug=ids.get("slug"),
                    )
                )

        # 2. Fetch discrete watch history events (up to 1000 items)
        history_data = await self._request("GET", "/sync/history/movies?limit=1000", user_id)
        watch_events: list[ProviderWatchEvent] = []
        if isinstance(history_data, list):
            for item in history_data:
                m_info = item.get("movie", {})
                ids = m_info.get("ids", {})
                m_item = ProviderMovieItem(
                    title=m_info.get("title", ""),
                    year=m_info.get("year"),
                    tmdb_id=ids.get("tmdb"),
                    imdb_id=ids.get("imdb"),
                    trakt_id=ids.get("trakt"),
                    letterboxd_slug=ids.get("slug"),
                )
                raw_watched_at = item.get("watched_at")
                if raw_watched_at:
                    try:
                        w_at = datetime.fromisoformat(raw_watched_at.replace("Z", "+00:00"))
                    except ValueError:
                        w_at = now
                else:
                    w_at = now

                event_id = str(item.get("id"))
                watch_events.append(
                    ProviderWatchEvent(
                        provider_movie=m_item,
                        watched_at=w_at,
                        provider_event_id=event_id,
                    )
                )

        # 3. Fetch ratings (Trakt integer 1-10 -> Canonical float 0.5-5.0)
        ratings_data = await self._request("GET", "/sync/ratings/movies", user_id)
        ratings: list[ProviderRating] = []
        if isinstance(ratings_data, list):
            for item in ratings_data:
                m_info = item.get("movie", {})
                ids = m_info.get("ids", {})
                m_item = ProviderMovieItem(
                    title=m_info.get("title", ""),
                    year=m_info.get("year"),
                    tmdb_id=ids.get("tmdb"),
                    imdb_id=ids.get("imdb"),
                    trakt_id=ids.get("trakt"),
                    letterboxd_slug=ids.get("slug"),
                )
                trakt_rating = item.get("rating")
                if trakt_rating is not None:
                    canonical_r = trakt_to_letterboxd(int(trakt_rating))
                    if canonical_r is not None:
                        raw_rated_at = item.get("rated_at")
                        r_at = None
                        if raw_rated_at:
                            try:
                                r_at = datetime.fromisoformat(raw_rated_at.replace("Z", "+00:00"))
                            except ValueError:
                                pass
                        ratings.append(
                            ProviderRating(
                                provider_movie=m_item,
                                rating=canonical_r,
                                rated_at=r_at,
                            )
                        )

        return ProviderSnapshot(
            provider="trakt",
            watched_movies=watched_movies,
            watch_events=watch_events,
            ratings=ratings,
            fetched_at=now,
        )

    def _build_trakt_movie_object(self, movie: ProviderMovieItem) -> dict:
        ids: dict[str, Any] = {}
        if movie.trakt_id:
            ids["trakt"] = movie.trakt_id
        if movie.tmdb_id:
            ids["tmdb"] = movie.tmdb_id
        if movie.imdb_id:
            ids["imdb"] = movie.imdb_id
        if movie.letterboxd_slug:
            ids["slug"] = movie.letterboxd_slug

        item: dict[str, Any] = {
            "title": movie.title,
            "ids": ids,
        }
        if movie.year:
            item["year"] = movie.year
        return item

    async def mark_watched(
        self,
        user_id: int,
        movie: ProviderMovieItem,
        watched_at: Optional[datetime] = None,
    ) -> bool:
        """Add movie viewing to Trakt history."""
        movie_obj = self._build_trakt_movie_object(movie)
        if watched_at:
            movie_obj["watched_at"] = watched_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        payload = {"movies": [movie_obj]}
        res = await self._request("POST", "/sync/history", user_id, json_data=payload)
        added = res.get("added", {}).get("movies", 0) if isinstance(res, dict) else 0
        return added > 0

    async def rate_movie(
        self,
        user_id: int,
        movie: ProviderMovieItem,
        canonical_rating: float,
        rated_at: Optional[datetime] = None,
    ) -> bool:
        """Submit rating to Trakt after converting from canonical 0.5-5.0 to 1-10."""
        trakt_rating_val = letterboxd_to_trakt(canonical_rating)
        movie_obj = self._build_trakt_movie_object(movie)
        movie_obj["rating"] = trakt_rating_val
        if rated_at:
            movie_obj["rated_at"] = rated_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        payload = {"movies": [movie_obj]}
        res = await self._request("POST", "/sync/ratings", user_id, json_data=payload)
        added = res.get("added", {}).get("movies", 0) if isinstance(res, dict) else 0
        return added > 0

    async def remove_rating(self, user_id: int, movie: ProviderMovieItem) -> bool:
        """Remove a movie rating from Trakt."""
        movie_obj = self._build_trakt_movie_object(movie)
        payload = {"movies": [movie_obj]}
        res = await self._request("POST", "/sync/ratings/remove", user_id, json_data=payload)
        deleted = res.get("deleted", {}).get("movies", 0) if isinstance(res, dict) else 0
        return deleted > 0
