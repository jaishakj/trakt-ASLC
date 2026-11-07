"""Integration tests for synchronization engine, duplicate event detection, and CSV import."""

import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.db.database import Base
from app.models.movie import Movie
from app.models.user import User
from app.models.watch_event import WatchEvent
from app.models.provider_activity import ProviderActivity
from app.providers.base import ProviderMovieItem, ProviderRating, ProviderSnapshot, ProviderWatchEvent
from app.providers.letterboxd import LetterboxdProvider
from app.services.csv import parse_csv_content
from app.sync.engine import SyncEngine


@pytest.fixture
async def async_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        # Create default user
        user = User(id=1)
        session.add(user)
        await session.commit()
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_event_detection_on_reimport(async_db: AsyncSession):
    """Importing the same Letterboxd CSV twice must NOT create duplicate watch events."""
    csv_sample = """Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date
Dune,2021,https://letterboxd.com/film/dune-2021/,4.5,No,,2026-01-04
Dune,2021,https://letterboxd.com/film/dune-2021/,4.5,Yes,,2026-03-10
"""
    rows = parse_csv_content(csv_sample)
    lb_prov = LetterboxdProvider(async_db)
    snapshot = lb_prov.build_snapshot_from_rows(rows)

    engine = SyncEngine(async_db, letterboxd_provider=lb_prov)

    # First sync run
    summary1 = await engine.execute_sync(user_id=1, letterboxd_snapshot=snapshot, dry_run=False, write_to_trakt=False)
    assert summary1.new_watch_events == 2

    # Verify database has 2 watch events
    we_res = await async_db.execute(select(WatchEvent).where(WatchEvent.user_id == 1))
    events = we_res.scalars().all()
    assert len(events) == 2

    # Second sync run with exact same data
    summary2 = await engine.execute_sync(user_id=1, letterboxd_snapshot=snapshot, dry_run=False, write_to_trakt=False)
    assert summary2.new_watch_events == 0  # No new events created!

    # Re-verify database still has only 2 watch events
    we_res2 = await async_db.execute(select(WatchEvent).where(WatchEvent.user_id == 1))
    events2 = we_res2.scalars().all()
    assert len(events2) == 2


@pytest.mark.asyncio
async def test_dry_run_does_not_mutate_state(async_db: AsyncSession):
    """Dry-run must not create movies, watch events, or provider activity in DB."""
    csv_sample = """Name,Year,tmdbID,Rating,Watched Date
Blade Runner,1982,78,5.0,2026-04-12
"""
    rows = parse_csv_content(csv_sample)
    lb_prov = LetterboxdProvider(async_db)
    snapshot = lb_prov.build_snapshot_from_rows(rows)

    engine = SyncEngine(async_db, letterboxd_provider=lb_prov)
    summary = await engine.execute_sync(user_id=1, letterboxd_snapshot=snapshot, dry_run=True)

    assert summary.new_watch_events == 1
    assert summary.rating_updates == 1

    # Verify database remains completely empty of movies and events
    movies = (await async_db.execute(select(Movie))).scalars().all()
    events = (await async_db.execute(select(WatchEvent))).scalars().all()
    assert len(movies) == 0
    assert len(events) == 0
