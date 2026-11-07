"""Pydantic schemas for conflict records and resolution."""

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict


class ConflictRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    movie_id: int
    movie_title: Optional[str] = None
    release_year: Optional[int] = None
    field: str
    trakt_value: Optional[str] = None
    letterboxd_value: Optional[str] = None
    previous_value: Optional[str] = None
    status: str
    resolution_choice: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime


class ResolveConflictRequest(BaseModel):
    resolution: Literal["trakt", "letterboxd", "previous", "custom"]
    custom_value: Optional[float] = None
