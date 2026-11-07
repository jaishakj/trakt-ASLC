"""Letterboxd CSV import and export routes."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ImportFormatError
from app.db.database import get_db
from app.models.user import User, Integration
from app.models.movie import Movie
from app.models.provider_activity import ProviderActivity
from app.models.watch_event import WatchEvent
from app.providers.letterboxd import LetterboxdProvider
from app.services.csv import parse_letterboxd_import, generate_letterboxd_export_csv
from app.sync.engine import SyncEngine

router = APIRouter(prefix="/api/letterboxd", tags=["letterboxd"])


@router.post("/import")
async def import_letterboxd_csv(
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="Simulate import without modifying database or Trakt"),
    write_to_trakt: bool = Query(True, description="Propagate imported Letterboxd changes to Trakt"),
    user_id: int = Query(1),
    db: AsyncSession = Depends(get_db),
):
    """Import Letterboxd CSV or ZIP archive.
    
    Parses diary.csv, ratings.csv, watched.csv, or unified import CSV.
    Safely merges watch events and canonical ratings.
    """
    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        rows = parse_letterboxd_import(content_bytes, file.filename or "import.csv")
    except ImportFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not rows:
        raise HTTPException(status_code=400, detail="No valid movie rows found in file")

    # Ensure user exists
    user = await db.get(User, user_id)
    if not user:
        user = User(id=user_id)
        db.add(user)
        await db.flush()

    # Build snapshot
    lb_provider = LetterboxdProvider(db)
    snapshot = lb_provider.build_snapshot_from_rows(rows)

    # Run sync engine
    engine = SyncEngine(db, letterboxd_provider=lb_provider)
    summary = await engine.execute_sync(
        user_id=user_id,
        letterboxd_snapshot=snapshot,
        dry_run=dry_run,
        write_to_trakt=write_to_trakt,
    )

    if not dry_run:
        # Mark Letterboxd integration as connected
        stmt = select(Integration).where(Integration.user_id == user_id, Integration.provider == "letterboxd")
        res = await db.execute(stmt)
        integration = res.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if not integration:
            integration = Integration(
                user_id=user_id,
                provider="letterboxd",
                connected_at=now,
            )
            db.add(integration)
        else:
            integration.updated_at = now
        await db.commit()

    return {
        "status": "dry_run_complete" if dry_run else "imported",
        "rows_parsed": len(rows),
        "summary": summary.to_dict(),
    }


@router.get("/export")
async def export_letterboxd_csv(
    user_id: int = Query(1),
    db: AsyncSession = Depends(get_db),
):
    """Export Trakt-originated activity and updates to a Letterboxd-compatible CSV file.
    
    Contains Title, Year, tmdbID, imdbID, Rating, and WatchedDate.
    """
    # Fetch watch events that originated from Trakt
    stmt = (
        select(WatchEvent, Movie)
        .join(Movie, WatchEvent.movie_id == Movie.id)
        .where(WatchEvent.user_id == user_id, WatchEvent.provider == "trakt")
    )
    res = await db.execute(stmt)
    records = res.all()

    # Also fetch ratings from Trakt provider_activity
    r_stmt = (
        select(ProviderActivity, Movie)
        .join(Movie, ProviderActivity.movie_id == Movie.id)
        .where(ProviderActivity.user_id == user_id, ProviderActivity.provider == "trakt")
    )
    r_res = await db.execute(r_stmt)
    ratings_map = {m.id: act.rating for act, m in r_res.all()}

    export_items: list[dict] = []
    seen_events: set[tuple[int, str]] = set()

    for we, m in records:
        date_str = we.watched_at.strftime("%Y-%m-%d")
        if (m.id, date_str) in seen_events:
            continue
        seen_events.add((m.id, date_str))

        export_items.append({
            "title": m.title,
            "year": m.release_year,
            "tmdb_id": m.tmdb_id,
            "imdb_id": m.imdb_id,
            "rating": ratings_map.get(m.id),
            "watched_date": we.watched_at,
        })

    # Include any rated movies that don't have a discrete watch event
    for act, m in r_res.all():
        if act.rating is not None and not any(item["title"] == m.title for item in export_items):
            export_items.append({
                "title": m.title,
                "year": m.release_year,
                "tmdb_id": m.tmdb_id,
                "imdb_id": m.imdb_id,
                "rating": act.rating,
                "watched_date": act.last_watched_at,
            })

    csv_content = generate_letterboxd_export_csv(export_items)
    filename = f"letterboxd_sync_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
