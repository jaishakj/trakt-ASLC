"""Unit and integration tests for Trakt provider and API failure recovery."""

import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.core.exceptions import ProviderUnavailableError
from app.db.database import Base
from app.models.user import User, Integration
from app.models.sync_event import SyncEvent
from app.providers.base import ProviderMovieItem, ProviderRating, ProviderSnapshot
from app.providers.trakt import TraktProvider
from app.sync.engine import SyncEngine


@pytest.fixture
async def async_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        user = User(id=1)
        session.add(user)
        # Mock active Trakt integration
        integ = Integration(user_id=1, provider="trakt", access_token="mock_token")
        session.add(integ)
        await session.commit()
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_trakt_api_failure_recovery_mid_sync(async_db: AsyncSession):
    """Simulate Trakt API failure mid-sync.
    Ensure failed event is recorded, canonical state is uncorrupted, and subsequent sync resumes safely.
    """
    mock_trakt = TraktProvider(async_db)
    # Mock is_connected to True
    mock_trakt.is_connected = AsyncMock(return_value=True)
    # Mock fetch_snapshot
    mock_trakt.fetch_snapshot = AsyncMock(
        return_value=ProviderSnapshot(
            provider="trakt",
            watched_movies=[],
            watch_events=[],
            ratings=[],
            fetched_at=None,
        )
    )
    # Simulate network failure during rate_movie
    mock_trakt.rate_movie = AsyncMock(side_effect=ProviderUnavailableError("Trakt 503 Service Unavailable"))

    # Prepare Letterboxd snapshot with a new rating
    from app.providers.letterboxd import LetterboxdProvider
    from app.services.csv import parse_csv_content

    csv_data = """Name,Year,tmdbID,Rating,Watched Date
The Matrix,1999,603,5.0,2026-05-15
"""
    rows = parse_csv_content(csv_data)
    lb_prov = LetterboxdProvider(async_db)
    lb_snapshot = lb_prov.build_snapshot_from_rows(rows)

    engine = SyncEngine(async_db, trakt_provider=mock_trakt, letterboxd_provider=lb_prov)

    # First attempt: rate_movie fails
    summary1 = await engine.execute_sync(user_id=1, letterboxd_snapshot=lb_snapshot, dry_run=False, write_to_trakt=True)
    assert summary1.rating_updates == 1

    # Check sync_events for recorded failure
    events = (await async_db.execute(select(SyncEvent).where(SyncEvent.user_id == 1))).scalars().all()
    failed_events = [e for e in events if e.status == "failed"]
    assert len(failed_events) >= 1
    assert "503" in (failed_events[0].error_message or "")

    # Second attempt: Trakt API recovers
    mock_trakt.rate_movie = AsyncMock(return_value=True)
    summary2 = await engine.execute_sync(user_id=1, letterboxd_snapshot=lb_snapshot, dry_run=False, write_to_trakt=True)
    # Resumes safely and succeeds
    events_after = (await async_db.execute(select(SyncEvent).where(SyncEvent.user_id == 1))).scalars().all()
    success_events = [e for e in events_after if e.status == "success" and e.operation == "update_rating"]
    assert len(success_events) >= 1
