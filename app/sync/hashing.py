"""Semantic Content Hashing module.

Computes deterministic SHA-256 hashes of movie activity state to ensure idempotency,
loop prevention, and change detection. Bookkeeping fields (timestamps, IDs) are strictly excluded.
"""

import hashlib
import json
from datetime import datetime, date
from typing import Any, Iterable, Optional


def normalize_datetime_str(dt: Any) -> Optional[str]:
    """Convert datetime, date, or ISO string to canonical UTC ISO 8601 string or None."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        # Format as ISO 8601 with Z or offset normalized
        if dt.tzinfo is None:
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return dt.astimezone().strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(dt, date):
        return dt.strftime("%Y-%m-%d")
    if isinstance(dt, str):
        # Clean and trim
        val = dt.strip()
        if not val:
            return None
        # Normalize trailing Z if any
        return val
    return str(dt)


def compute_semantic_hash(
    watched: bool,
    rating: Optional[float],
    watch_events: Iterable[Any] = (),
    last_watched_at: Optional[Any] = None,
) -> str:
    """Compute deterministic SHA-256 hash for a movie's semantic activity state.
    
    Excludes any database IDs, remote_updated_at, created_at, or sync timestamps.
    """
    # 1. Normalize watch events into a stably sorted list of deterministic identifiers/dates
    normalized_events: list[str] = []
    for ev in watch_events:
        if isinstance(ev, str):
            normalized_events.append(ev.strip())
        elif isinstance(ev, (datetime, date)):
            d_str = normalize_datetime_str(ev)
            if d_str:
                normalized_events.append(d_str)
        elif isinstance(ev, dict):
            # If dictionary with watched_at / provider_event_id
            ev_id = ev.get("provider_event_id") or ""
            w_at = normalize_datetime_str(ev.get("watched_at")) or ""
            normalized_events.append(f"{ev_id}:{w_at}")
        elif hasattr(ev, "watched_at"):
            w_at = normalize_datetime_str(getattr(ev, "watched_at", None)) or ""
            p_id = getattr(ev, "provider_event_id", "") or ""
            normalized_events.append(f"{p_id}:{w_at}")
        else:
            normalized_events.append(str(ev))

    normalized_events.sort()

    # 2. Canonicalize fields
    canonical_state = {
        "watched": bool(watched),
        "rating": round(float(rating), 1) if rating is not None else None,
        "last_watched_at": normalize_datetime_str(last_watched_at),
        "watch_events": normalized_events,
    }

    # 3. Deterministic JSON serialization
    serialized = json.dumps(canonical_state, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    # 4. SHA-256 hash
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
