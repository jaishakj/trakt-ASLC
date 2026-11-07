"""Unit and integration tests for deterministic idempotency enforcement."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.db.database import Base
from app.models.user import User
from app.providers.letterboxd import LetterboxdProvider
from app.services.csv import parse_csv_content
from app.sync.engine import SyncEngine
from app.sync.idempotency import generate_idempotency_key


def test_idempotency_key_deterministic_and_clean():
    """Ensure key generation has no timestamps, UUIDs, or nondeterminism."""
    k1 = generate_idempotency_key(1, 10, "trakt", "letterboxd", "update_rating", "abc123hash")
    k2 = generate_idempotency_key(1, 10, "trakt", "letterboxd", "update_rating", "abc123hash")
    assert k1 == k2
    assert k1 == "1:10:trakt:letterboxd:update_rating:abc123hash"


@pytest.fixture
async def async_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        user = User(id=1)
        session.add(user)
        await session.commit()
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_repeated_sync_yields_zero_additional_changes(async_db: AsyncSession):
    """Running sync() sync() sync() repeatedly must produce 0 changes after the first run."""
    csv_sample = """Name,Year,tmdbID,Rating,Watched Date
Heat,1995,949,4.5,2026-06-01
"""
    rows = parse_csv_content(csv_sample)
    lb_prov = LetterboxdProvider(async_db)
    snapshot = lb_prov.build_snapshot_from_rows(rows)

    engine = SyncEngine(async_db, letterboxd_provider=lb_prov)

    # First run
    s1 = await engine.execute_sync(user_id=1, letterboxd_snapshot=snapshot, dry_run=False, write_to_trakt=False)
    assert s1.new_watch_events == 1
    assert s1.rating_updates == 1

    # Runs 2, 3, 4
    for _ in range(3):
        s = await engine.execute_sync(user_id=1, letterboxd_snapshot=snapshot, dry_run=False, write_to_trakt=False)
        assert s.new_watch_events == 0
        assert s.rating_updates == 0
        assert s.unchanged >= 1
