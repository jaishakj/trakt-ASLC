"""Synchronization endpoints: execute sync, dry-run, events, and watch history."""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.movie import Movie
from app.models.sync_event import SyncEvent
from app.models.watch_event import WatchEvent
from app.schemas.activity import WatchEventOut
from app.schemas.sync import DryRunResponse, SyncEventOut, SyncTriggerRequest
from app.sync.engine import SyncEngine

router = APIRouter(prefix="/api", tags=["sync"])


@router.post("/sync")
async def trigger_sync(
    payload: Optional[SyncTriggerRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """Trigger manual synchronization between Trakt and Letterboxd."""
    user_id = payload.user_id if payload else 1
    write_to_trakt = payload.write_to_trakt if payload else True

    engine = SyncEngine(db)
    summary = await engine.execute_sync(
        user_id=user_id,
        dry_run=False,
        write_to_trakt=write_to_trakt,
    )
    return {"status": "success", "summary": summary.to_dict()}


@router.post("/sync/dry-run", response_model=DryRunResponse)
async def trigger_dry_run(
    payload: Optional[SyncTriggerRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """Run a dry-run synchronization simulation without modifying Trakt or database."""
    user_id = payload.user_id if payload else 1
    engine = SyncEngine(db)
    summary = await engine.execute_sync(
        user_id=user_id,
        dry_run=True,
        write_to_trakt=False,
    )
    return DryRunResponse(
        new_watch_events=summary.new_watch_events,
        rating_updates=summary.rating_updates,
        equivalent_ratings=summary.equivalent_ratings,
        conflicts=summary.conflicts,
        unchanged=summary.unchanged,
        unmatched_movies=summary.unmatched_movies,
        trakt_movies_count=summary.trakt_movies_count,
        letterboxd_movies_count=summary.letterboxd_movies_count,
    )


@router.get("/sync/events", response_model=list[SyncEventOut])
async def list_sync_events(
    limit: int = Query(50, ge=1, le=500),
    user_id: int = Query(1),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve audit ledger of synchronization events."""
    stmt = (
        select(SyncEvent)
        .where(SyncEvent.user_id == user_id)
        .order_by(desc(SyncEvent.created_at))
        .limit(limit)
    )
    res = await db.execute(stmt)
    return list(res.scalars())


@router.get("/watch-events", response_model=list[WatchEventOut])
async def list_watch_events(
    limit: int = Query(100, ge=1, le=1000),
    user_id: int = Query(1),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve discrete movie watch events with viewing timestamps."""
    stmt = (
        select(WatchEvent, Movie)
        .join(Movie, WatchEvent.movie_id == Movie.id)
        .where(WatchEvent.user_id == user_id)
        .order_by(desc(WatchEvent.watched_at))
        .limit(limit)
    )
    res = await db.execute(stmt)
    results = []
    for we, m in res.all():
        results.append(
            WatchEventOut(
                id=we.id,
                user_id=we.user_id,
                movie_id=we.movie_id,
                movie_title=m.title,
                release_year=m.release_year,
                provider=we.provider,
                provider_event_id=we.provider_event_id,
                watched_at=we.watched_at,
                created_at=we.created_at,
            )
        )
    return results
