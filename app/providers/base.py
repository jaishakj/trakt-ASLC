"""Normalized Provider Interface.

Defines the contract that any movie tracking provider (Trakt, Letterboxd, future providers)
must implement. The sync engine interacts exclusively with this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class ProviderMovieItem:
    """Normalized representation of a movie from a provider."""
    title: str
    year: Optional[int] = None
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    trakt_id: Optional[int] = None
    letterboxd_slug: Optional[str] = None
    raw_provider_id: Optional[str] = None


@dataclass
class ProviderWatchEvent:
    """Normalized watch event from a provider."""
    provider_movie: ProviderMovieItem
    watched_at: datetime
    provider_event_id: str
    source_event_id: Optional[str] = None


@dataclass
class ProviderRating:
    """Normalized rating from a provider.
    
    IMPORTANT: rating MUST be normalized to the canonical Letterboxd scale (0.5 to 5.0)
    by the provider adapter before returning!
    """
    provider_movie: ProviderMovieItem
    rating: float  # Canonical 0.5 - 5.0 scale
    rated_at: Optional[datetime] = None


@dataclass
class ProviderSnapshot:
    """Complete activity snapshot fetched or parsed from a provider."""
    provider: str
    watched_movies: list[ProviderMovieItem]
    watch_events: list[ProviderWatchEvent]
    ratings: list[ProviderRating]
    fetched_at: datetime


class Provider(ABC):
    """Abstract Base Class for external providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g. 'trakt', 'letterboxd')."""
        pass

    @abstractmethod
    async def is_connected(self, user_id: int) -> bool:
        """Check if provider is authenticated and operational for the given user."""
        pass

    @abstractmethod
    async def fetch_snapshot(self, user_id: int) -> ProviderSnapshot:
        """Fetch all watched movies, watch events, and ratings in canonical representation."""
        pass

    @abstractmethod
    async def mark_watched(
        self,
        user_id: int,
        movie: ProviderMovieItem,
        watched_at: Optional[datetime] = None,
    ) -> bool:
        """Record a watch event in the provider."""
        pass

    @abstractmethod
    async def rate_movie(
        self,
        user_id: int,
        movie: ProviderMovieItem,
        canonical_rating: float,
        rated_at: Optional[datetime] = None,
    ) -> bool:
        """Submit a rating using canonical (0.5 - 5.0) scale."""
        pass

    @abstractmethod
    async def remove_rating(self, user_id: int, movie: ProviderMovieItem) -> bool:
        """Remove a rating from the provider."""
        pass
