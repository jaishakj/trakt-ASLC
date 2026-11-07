"""Conflict management and resolution routes."""

import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.movie import Movie
from app.models.provider_activity import ProviderActivity
from app.models.sync_event import ConflictRecord, SyncEvent
from app.providers.trakt import TraktProvider
from app.providers.base import ProviderMovieItem
from app.schemas.conflicts import ConflictRecordOut, ResolveConflictRequest
from app.sync.hashing import compute_semantic_hash
from app.sync.idempotency import generate_idempotency_key
from app.sync.rating_scale import validate_canonical_rating

router = APIRouter(prefix="/api/conflicts", tags=["conflicts"])


@router.get("", response_model=list[ConflictRecordOut])
async def list_conflicts(
    status: Optional[str] = Query("pending", description="Filter by 'pending', 'resolved', or null for all"),
    user_id: int = Query(1),
    db: AsyncSession = Depends(get_db),
):
    """List detected sync conflicts."""
    stmt = (
        select(ConflictRecord, Movie)
        .join(Movie, ConflictRecord.movie_id == Movie.id)
        .where(ConflictRecord.user_id == user_id)
    )
    if status:
        stmt = stmt.where(ConflictRecord.status == status)
    stmt = stmt.order_by(desc(ConflictRecord.created_at))

    res = await db.execute(stmt)
    results = []
    for conf, m in res.all():
        results.append(
            ConflictRecordOut(
                id=conf.id,
                user_id=conf.user_id,
                movie_id=conf.movie_id,
                movie_title=m.title,
                release_year=m.release_year,
                field=conf.field,
                trakt_value=conf.trakt_value,
                letterboxd_value=conf.letterboxd_value,
                previous_value=conf.previous_value,
                status=conf.status,
                resolution_choice=conf.resolution_choice,
                resolved_at=conf.resolved_at,
                created_at=conf.created_at,
            )
        )
    return results


@router.post("/{conflict_id}/resolve")
async def resolve_conflict(
    conflict_id: int,
    payload: ResolveConflictRequest,
    db: AsyncSession = Depends(get_db),
):
    """Resolve a pending sync conflict by selecting an authoritative source or custom value."""
    conflict = await db.get(ConflictRecord, conflict_id)
    if not conflict:
        raise HTTPException(status_code=404, detail="Conflict record not found")

    if conflict.status == "resolved":
        return {"status": "already_resolved", "conflict_id": conflict_id}

    movie = await db.get(Movie, conflict.movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Associated movie not found")

    # Determine chosen value
    resolved_val: Optional[float] = None
    if payload.resolution == "trakt":
        resolved_val = float(conflict.trakt_value) if conflict.trakt_value else None
    elif payload.resolution == "letterboxd":
        resolved_val = float(conflict.letterboxd_value) if conflict.letterboxd_value else None
    elif payload.resolution == "previous":
        resolved_val = float(conflict.previous_value) if conflict.previous_value else None
    elif payload.resolution == "custom":
        if payload.custom_value is None:
            raise HTTPException(status_code=400, detail="custom_value must be provided for 'custom' resolution")
        resolved_val = validate_canonical_rating(payload.custom_value)

    # 1. Update ProviderActivity snapshots
    act_stmt = select(ProviderActivity).where(
        ProviderActivity.user_id == conflict.user_id,
        ProviderActivity.movie_id == movie.id,
    )
    act_res = await db.execute(act_stmt)
    activities = {act.provider: act for act in act_res.scalars()}

    now = datetime.now(timezone.utc)
    content_hash = compute_semantic_hash(watched=True, rating=resolved_val)

    for prov in ("trakt", "letterboxd"):
        if prov in activities:
            activities[prov].rating = resolved_val
            activities[prov].content_hash = content_hash
            activities[prov].updated_at = now
        else:
            new_act = ProviderActivity(
                user_id=conflict.user_id,
                movie_id=movie.id,
                provider=prov,
                watched=True,
                rating=resolved_val,
                content_hash=content_hash,
                last_seen_at=now,
            )
            db.add(new_act)

    # 2. If decision requires writing to Trakt
    if payload.resolution in ("letterboxd", "custom") and resolved_val is not None:
        trakt = TraktProvider(db)
        if await trakt.is_connected(conflict.user_id):
            p_movie = ProviderMovieItem(
                title=movie.title,
                year=movie.release_year,
                tmdb_id=movie.tmdb_id,
                imdb_id=movie.imdb_id,
                trakt_id=movie.trakt_id,
            )
            try:
                await trakt.rate_movie(conflict.user_id, p_movie, resolved_val)
            except Exception as e:
                pass

    # 3. Record SyncEvent
    idem_key = generate_idempotency_key(
        conflict.user_id, movie.id, "conflict_resolver", "canonical", "resolve_rating", content_hash
    )
    sync_ev = SyncEvent(
        user_id=conflict.user_id,
        movie_id=movie.id,
        source_provider="conflict_resolver",
        destination_provider="canonical",
        operation="resolve_rating",
        status="success",
        new_state=json.dumps({"resolved_rating": resolved_val, "choice": payload.resolution}),
        content_hash=content_hash,
        idempotency_key=idem_key,
    )
    db.add(sync_ev)

    # 4. Mark conflict record resolved
    conflict.status = "resolved"
    conflict.resolution_choice = payload.resolution
    conflict.resolved_at = now

    await db.commit()
    return {
        "status": "resolved",
        "conflict_id": conflict_id,
        "resolution": payload.resolution,
        "resolved_value": resolved_val,
    }
