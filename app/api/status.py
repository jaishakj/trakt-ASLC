"""System status, integrations, settings, and health check endpoints."""

from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db
from app.models.movie import Movie
from app.models.sync_event import ConflictRecord, SyncEvent
from app.models.user import Integration
from app.models.watch_event import WatchEvent
from app.schemas.sync import ServiceStatusResponse
from app.services.scheduler import last_job_run, last_job_status, scheduler

router = APIRouter(tags=["status"])


@router.get("/health")
async def health_check():
    """Liveness probe."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/api/status", response_model=ServiceStatusResponse)
async def get_service_status(
    user_id: int = 1,
    db: AsyncSession = Depends(get_db),
):
    """Overall system operational status."""
    # Check integrations
    int_stmt = select(Integration).where(Integration.user_id == user_id)
    int_res = await db.execute(int_stmt)
    integrations = {i.provider: i for i in int_res.scalars()}

    trakt_connected = "trakt" in integrations and integrations["trakt"].access_token is not None
    lb_connected = "letterboxd" in integrations

    last_trakt = integrations["trakt"].updated_at if "trakt" in integrations else None
    last_lb = integrations["letterboxd"].updated_at if "letterboxd" in integrations else None

    # Counts
    movies_count = (await db.execute(select(func.count(Movie.id)))).scalar_one()
    watch_events_count = (
        await db.execute(select(func.count(WatchEvent.id)).where(WatchEvent.user_id == user_id))
    ).scalar_one()
    conflicts_count = (
        await db.execute(
            select(func.count(ConflictRecord.id)).where(
                ConflictRecord.user_id == user_id, ConflictRecord.status == "pending"
            )
        )
    ).scalar_one()

    return ServiceStatusResponse(
        status="healthy",
        trakt_connected=trakt_connected,
        letterboxd_connected=lb_connected,
        last_trakt_sync=last_trakt,
        last_letterboxd_import=last_lb,
        movies_count=movies_count,
        watch_events_count=watch_events_count,
        pending_conflicts_count=conflicts_count,
        scheduler_running=scheduler.running,
        sync_interval_minutes=settings.SYNC_INTERVAL_MINUTES,
    )


@router.get("/api/integrations")
async def list_integrations(
    user_id: int = 1,
    db: AsyncSession = Depends(get_db),
):
    """List connected provider integrations (tokens strictly masked)."""
    stmt = select(Integration).where(Integration.user_id == user_id)
    res = await db.execute(stmt)
    integrations = res.scalars().all()

    return [
        {
            "id": i.id,
            "provider": i.provider,
            "is_connected": i.access_token is not None if i.provider == "trakt" else True,
            "connected_at": i.connected_at,
            "updated_at": i.updated_at,
            "has_refresh_token": i.refresh_token is not None,
            "token_expires_at": i.token_expires_at,
        }
        for i in integrations
    ]


class SettingsPayload(BaseModel):
    sync_interval_minutes: Optional[int] = None
    letterboxd_username: Optional[str] = None


@router.get("/api/settings")
async def get_settings():
    """Retrieve non-secret runtime configuration."""
    return {
        "sync_interval_minutes": settings.SYNC_INTERVAL_MINUTES,
        "letterboxd_username": settings.LETTERBOXD_USERNAME,
        "trakt_client_id_configured": bool(settings.TRAKT_CLIENT_ID),
        "tmdb_api_key_configured": bool(settings.TMDB_API_KEY),
    }


@router.post("/api/settings")
async def update_settings(payload: SettingsPayload):
    """Update runtime settings."""
    if payload.sync_interval_minutes is not None and payload.sync_interval_minutes > 0:
        settings.SYNC_INTERVAL_MINUTES = payload.sync_interval_minutes
    if payload.letterboxd_username is not None:
        settings.LETTERBOXD_USERNAME = payload.letterboxd_username

    return {"status": "updated", "settings": await get_settings()}
