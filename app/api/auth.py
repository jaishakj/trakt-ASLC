"""Trakt OAuth authentication routes."""

import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ProviderAuthError
from app.db.database import get_db
from app.models.user import User, Integration
from app.providers.trakt import TraktProvider
from app.services.encryption import encrypt_token

router = APIRouter(tags=["auth"])

# State verification cache (in-memory for MVP)
_oauth_states: set[str] = set()


@router.get("/auth/trakt")
async def start_trakt_oauth():
    """Initiate Trakt OAuth flow."""
    state = secrets.token_urlsafe(16)
    _oauth_states.add(state)
    trakt = TraktProvider()
    auth_url = trakt.get_authorization_url(state)
    return {"authorization_url": auth_url, "state": state}


@router.get("/auth/trakt/callback")
async def trakt_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Handle Trakt OAuth callback."""
    if state not in _oauth_states:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state parameter")
    _oauth_states.remove(state)

    trakt = TraktProvider(db)
    try:
        token_data = await trakt.exchange_code_for_token(code)
    except ProviderAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 7776000)

    # Ensure default user (ID 1) exists
    user = await db.get(User, 1)
    if not user:
        user = User(id=1)
        db.add(user)
        await db.flush()

    # Save integration
    stmt = select(Integration).where(Integration.user_id == 1, Integration.provider == "trakt")
    res = await db.execute(stmt)
    integration = res.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if not integration:
        integration = Integration(
            user_id=1,
            provider="trakt",
            access_token=encrypt_token(access_token),
            refresh_token=encrypt_token(refresh_token),
            token_expires_at=now + timedelta(seconds=expires_in),
            connected_at=now,
        )
        db.add(integration)
    else:
        integration.access_token = encrypt_token(access_token)
        integration.refresh_token = encrypt_token(refresh_token)
        integration.token_expires_at = now + timedelta(seconds=expires_in)
        integration.updated_at = now

    await db.commit()
    return RedirectResponse(url="/?trakt_connected=1", status_code=303)
