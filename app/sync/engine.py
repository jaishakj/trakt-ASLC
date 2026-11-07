"""Three-way synchronization engine.

Coordinates Trakt and Letterboxd synchronization, enforcing:
- Safe merge of watch events (never auto-deleting watches)
- Canonical rating conversion and three-way conflict detection
- Semantic content hashing for idempotency and loop prevention
- Dry-run capability
- Detailed structured event logging
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SyncConflictError
from app.models.movie import Movie, MovieMapping
from app.models.provider_activity import ProviderActivity
from app.models.sync_event import SyncEvent, ConflictRecord
from app.models.watch_event import WatchEvent, derive_event_id
from app.providers.base import ProviderMovieItem, ProviderSnapshot
from app.providers.trakt import TraktProvider
from app.providers.letterboxd import LetterboxdProvider
from app.sync.conflict import ConflictResolutionResult, compare_ratings_three_way
from app.sync.hashing import compute_semantic_hash
from app.sync.idempotency import generate_idempotency_key
from app.sync.matcher import resolve_movie
from app.sync.rating_scale import ratings_are_equivalent

logger = logging.getLogger(__name__)


@dataclass
class SyncSummary:
    new_watch_events: int = 0
    rating_updates: int = 0
    equivalent_ratings: int = 0
    conflicts: int = 0
    unchanged: int = 0
    unmatched_movies: int = 0
    trakt_movies_count: int = 0
    letterboxd_movies_count: int = 0
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "new_watch_events": self.new_watch_events,
            "rating_updates": self.rating_updates,
            "equivalent_ratings": self.equivalent_ratings,
            "conflicts": self.conflicts,
            "unchanged": self.unchanged,
            "unmatched_movies": self.unmatched_movies,
            "trakt_movies_count": self.trakt_movies_count,
            "letterboxd_movies_count": self.letterboxd_movies_count,
            "details": self.details,
        }


class SyncEngine:
    def __init__(
        self,
        db: AsyncSession,
        trakt_provider: Optional[TraktProvider] = None,
        letterboxd_provider: Optional[LetterboxdProvider] = None,
    ):
        self.db = db
        self.trakt = trakt_provider or TraktProvider(db)
        self.letterboxd = letterboxd_provider or LetterboxdProvider(db)

    async def _get_or_create_movie(
        self,
        user_id: int,
        p_movie: ProviderMovieItem,
        known_movies_cache: dict[str, Movie],
    ) -> tuple[Optional[Movie], float]:
        """Resolve or persist Movie entity with high-confidence matching."""
        # 1. Check local lookup cache by identifiers
        if p_movie.tmdb_id and f"tmdb:{p_movie.tmdb_id}" in known_movies_cache:
            return known_movies_cache[f"tmdb:{p_movie.tmdb_id}"], 1.00
        if p_movie.imdb_id and f"imdb:{p_movie.imdb_id}" in known_movies_cache:
            return known_movies_cache[f"imdb:{p_movie.imdb_id}"], 1.00
        if p_movie.trakt_id and f"trakt:{p_movie.trakt_id}" in known_movies_cache:
            return known_movies_cache[f"trakt:{p_movie.trakt_id}"], 1.00

        # 2. Query database for existing movie with matching external IDs
        conditions = []
        if p_movie.tmdb_id:
            conditions.append(Movie.tmdb_id == p_movie.tmdb_id)
        if p_movie.imdb_id:
            conditions.append(Movie.imdb_id == p_movie.imdb_id)
        if p_movie.trakt_id:
            conditions.append(Movie.trakt_id == p_movie.trakt_id)

        matched_movie: Optional[Movie] = None
        if conditions:
            from sqlalchemy import or_
            stmt = select(Movie).where(or_(*conditions))
            res = await self.db.execute(stmt)
            matched_movie = res.scalars().first()

        # 3. If no external ID match, try title and year resolution
        confidence = 1.00
        if not matched_movie:
            identity = resolve_movie(
                title=p_movie.title,
                year=p_movie.year,
                tmdb_id=p_movie.tmdb_id,
                imdb_id=p_movie.imdb_id,
                trakt_id=p_movie.trakt_id,
                letterboxd_slug=p_movie.letterboxd_slug,
            )
            confidence = identity.confidence

            # Re-check database by title + year
            if p_movie.title:
                t_stmt = select(Movie).where(
                    Movie.title.ilike(p_movie.title.strip()),
                    Movie.release_year == p_movie.year if p_movie.year else True,
                )
                t_res = await self.db.execute(t_stmt)
                matched_movie = t_res.scalars().first()

        if matched_movie:
            # Update missing external IDs if new one discovered
            updated = False
            if not matched_movie.tmdb_id and p_movie.tmdb_id:
                matched_movie.tmdb_id = p_movie.tmdb_id
                updated = True
            if not matched_movie.imdb_id and p_movie.imdb_id:
                matched_movie.imdb_id = p_movie.imdb_id
                updated = True
            if not matched_movie.trakt_id and p_movie.trakt_id:
                matched_movie.trakt_id = p_movie.trakt_id
                updated = True
            if not matched_movie.letterboxd_slug and p_movie.letterboxd_slug:
                matched_movie.letterboxd_slug = p_movie.letterboxd_slug
                updated = True

            # Cache
            if matched_movie.tmdb_id:
                known_movies_cache[f"tmdb:{matched_movie.tmdb_id}"] = matched_movie
            if matched_movie.imdb_id:
                known_movies_cache[f"imdb:{matched_movie.imdb_id}"] = matched_movie
            if matched_movie.trakt_id:
                known_movies_cache[f"trakt:{matched_movie.trakt_id}"] = matched_movie
            return matched_movie, confidence

        # If confidence is below threshold, reject automatic creation
        if confidence < 0.80 and not (p_movie.tmdb_id or p_movie.imdb_id or p_movie.trakt_id):
            return None, confidence

        # Create new Movie record
        movie = Movie(
            title=p_movie.title or "Unknown Title",
            release_year=p_movie.year,
            tmdb_id=p_movie.tmdb_id,
            imdb_id=p_movie.imdb_id,
            trakt_id=p_movie.trakt_id,
            letterboxd_slug=p_movie.letterboxd_slug,
        )
        self.db.add(movie)
        await self.db.flush()

        # Cache
        if movie.tmdb_id:
            known_movies_cache[f"tmdb:{movie.tmdb_id}"] = movie
        if movie.imdb_id:
            known_movies_cache[f"imdb:{movie.imdb_id}"] = movie
        if movie.trakt_id:
            known_movies_cache[f"trakt:{movie.trakt_id}"] = movie

        return movie, confidence

    async def execute_sync(
        self,
        user_id: int,
        letterboxd_snapshot: Optional[ProviderSnapshot] = None,
        dry_run: bool = False,
        write_to_trakt: bool = True,
    ) -> SyncSummary:
        """Run three-way synchronization.
        
        If dry_run is True, computes all actions and returns summary without writing
        to Trakt, mutating canonical database state, or recording success sync events.
        """
        summary = SyncSummary()
        known_movies_cache: dict[str, Movie] = {}

        # 1. Fetch Trakt snapshot if Trakt is connected
        trakt_snapshot: Optional[ProviderSnapshot] = None
        if await self.trakt.is_connected(user_id):
            try:
                trakt_snapshot = await self.trakt.fetch_snapshot(user_id)
                summary.trakt_movies_count = len(trakt_snapshot.watched_movies)
            except Exception as e:
                logger.error(f"Failed to fetch Trakt snapshot: {e}")
                if not dry_run:
                    raise

        # 2. Letterboxd snapshot (passed in from import or loaded from DB)
        if letterboxd_snapshot is None:
            letterboxd_snapshot = await self.letterboxd.fetch_snapshot(user_id)
        summary.letterboxd_movies_count = len(letterboxd_snapshot.watched_movies)

        # Build lookup tables for Trakt data by key
        trakt_ratings_map: dict[str, float] = {}
        trakt_watch_events_map: dict[str, list[Any]] = {}
        if trakt_snapshot:
            for r in trakt_snapshot.ratings:
                k = f"{r.provider_movie.tmdb_id or ''}:{r.provider_movie.imdb_id or ''}:{r.provider_movie.title.lower()}"
                trakt_ratings_map[k] = r.rating

            for we in trakt_snapshot.watch_events:
                k = f"{we.provider_movie.tmdb_id or ''}:{we.provider_movie.imdb_id or ''}:{we.provider_movie.title.lower()}"
                trakt_watch_events_map.setdefault(k, []).append(we)

        # Build lookup tables for Letterboxd data
        lb_ratings_map: dict[str, float] = {}
        lb_watch_events_map: dict[str, list[Any]] = {}
        for r in letterboxd_snapshot.ratings:
            k = f"{r.provider_movie.tmdb_id or ''}:{r.provider_movie.imdb_id or ''}:{r.provider_movie.title.lower()}"
            lb_ratings_map[k] = r.rating

        for we in letterboxd_snapshot.watch_events:
            k = f"{we.provider_movie.tmdb_id or ''}:{we.provider_movie.imdb_id or ''}:{we.provider_movie.title.lower()}"
            lb_watch_events_map.setdefault(k, []).append(we)

        # Combine all unique movies across both providers
        all_movies_items: list[tuple[ProviderMovieItem, str]] = []
        seen_keys: set[str] = set()

        if trakt_snapshot:
            for m in trakt_snapshot.watched_movies:
                k = f"{m.tmdb_id or ''}:{m.imdb_id or ''}:{m.title.lower()}"
                if k not in seen_keys:
                    seen_keys.add(k)
                    all_movies_items.append((m, "trakt"))

        for m in letterboxd_snapshot.watched_movies:
            k = f"{m.tmdb_id or ''}:{m.imdb_id or ''}:{m.title.lower()}"
            if k not in seen_keys:
                seen_keys.add(k)
                all_movies_items.append((m, "letterboxd"))

        # Process each movie
        for p_movie, src_origin in all_movies_items:
            m_key = f"{p_movie.tmdb_id or ''}:{p_movie.imdb_id or ''}:{p_movie.title.lower()}"

            # Movie resolution
            movie: Optional[Movie] = None
            if not dry_run:
                movie, conf = await self._get_or_create_movie(user_id, p_movie, known_movies_cache)
                if not movie:
                    summary.unmatched_movies += 1
                    continue
            else:
                conf = 1.0 if (p_movie.tmdb_id or p_movie.imdb_id) else 0.85
                if conf < 0.80:
                    summary.unmatched_movies += 1
                    continue

            # Load baseline provider_activity if exists
            baseline_trakt: Optional[ProviderActivity] = None
            baseline_lb: Optional[ProviderActivity] = None
            existing_watch_events: list[WatchEvent] = []

            if movie and not dry_run:
                # Load baseline activities
                b_stmt = select(ProviderActivity).where(
                    ProviderActivity.user_id == user_id,
                    ProviderActivity.movie_id == movie.id,
                )
                b_res = await self.db.execute(b_stmt)
                for b_act in b_res.scalars():
                    if b_act.provider == "trakt":
                        baseline_trakt = b_act
                    elif b_act.provider == "letterboxd":
                        baseline_lb = b_act

                # Load existing watch events
                w_stmt = select(WatchEvent).where(
                    WatchEvent.user_id == user_id,
                    WatchEvent.movie_id == movie.id,
                )
                w_res = await self.db.execute(w_stmt)
                existing_watch_events = list(w_res.scalars())

            # Evaluate Ratings
            trakt_r = trakt_ratings_map.get(m_key)
            lb_r = lb_ratings_map.get(m_key)
            t_base = baseline_trakt.rating if baseline_trakt else None
            lb_base = baseline_lb.rating if baseline_lb else None

            is_lb_unchanged = (baseline_lb is not None and ratings_are_equivalent(baseline_lb.rating, lb_r))

            if trakt_snapshot is None and is_lb_unchanged:
                res = ConflictResolutionResult(
                    has_conflict=False,
                    resolved_value=lb_r,
                    action_for_trakt="none",
                    action_for_letterboxd="none",
                    reason="Letterboxd rating unchanged from baseline; Trakt not connected",
                )
            else:
                res = compare_ratings_three_way(
                    trakt_rating=trakt_r,
                    letterboxd_rating=lb_r,
                    trakt_baseline=t_base,
                    letterboxd_baseline=lb_base,
                )

            is_trakt_action = (res.action_for_trakt == "update_rating" and trakt_snapshot is not None)
            is_lb_action = (res.action_for_letterboxd == "export_rating")

            if res.has_conflict:
                summary.conflicts += 1
                if not dry_run and movie:
                    # Record conflict in DB
                    conf_record = ConflictRecord(
                        user_id=user_id,
                        movie_id=movie.id,
                        field="rating",
                        trakt_value=str(trakt_r) if trakt_r is not None else None,
                        letterboxd_value=str(lb_r) if lb_r is not None else None,
                        previous_value=str(t_base or lb_base) if (t_base or lb_base) is not None else None,
                        status="pending",
                    )
                    self.db.add(conf_record)
            elif ratings_are_equivalent(trakt_r, lb_r) and trakt_r is not None:
                summary.equivalent_ratings += 1
            elif res.action_for_trakt == "update_rating" or res.action_for_letterboxd == "export_rating":
                if dry_run:
                    summary.rating_updates += 1
                elif movie:
                    if res.action_for_trakt == "update_rating" and write_to_trakt and trakt_snapshot:
                        # Write to Trakt
                        content_hash = compute_semantic_hash(watched=True, rating=res.resolved_value)
                        idem_key = generate_idempotency_key(
                            user_id, movie.id, "letterboxd", "trakt", "update_rating", content_hash
                        )
                        # Check idempotency
                        chk = await self.db.execute(select(SyncEvent).where(SyncEvent.idempotency_key == idem_key))
                        existing_ev = chk.scalar_one_or_none()
                        if existing_ev and existing_ev.status == "success":
                            # Already successfully synced to Trakt in previous run!
                            pass
                        elif not existing_ev or existing_ev.status == "failed":
                            summary.rating_updates += 1
                            try:
                                await self.trakt.rate_movie(user_id, p_movie, res.resolved_value)
                                if existing_ev:
                                    existing_ev.status = "success"
                                    existing_ev.error_message = None
                                    existing_ev.new_state = json.dumps({"rating": res.resolved_value})
                                else:
                                    sync_ev = SyncEvent(
                                        user_id=user_id,
                                        movie_id=movie.id,
                                        source_provider="letterboxd",
                                        destination_provider="trakt",
                                        operation="update_rating",
                                        status="success",
                                        new_state=json.dumps({"rating": res.resolved_value}),
                                        content_hash=content_hash,
                                        idempotency_key=idem_key,
                                    )
                                    self.db.add(sync_ev)
                            except Exception as ex:
                                if existing_ev:
                                    existing_ev.error_message = str(ex)
                                else:
                                    sync_ev = SyncEvent(
                                        user_id=user_id,
                                        movie_id=movie.id,
                                        source_provider="letterboxd",
                                        destination_provider="trakt",
                                        operation="update_rating",
                                        status="failed",
                                        error_message=str(ex),
                                        content_hash=content_hash,
                                        idempotency_key=idem_key,
                                    )
                                    self.db.add(sync_ev)
                    elif res.action_for_letterboxd == "export_rating":
                        summary.rating_updates += 1
                        await self.letterboxd.rate_movie(
                            user_id=user_id,
                            movie=p_movie,
                            canonical_rating=res.resolved_value,
                        )
                    elif not is_lb_unchanged:
                        summary.rating_updates += 1

            # Evaluate Watch Events
            t_events = trakt_watch_events_map.get(m_key, [])
            lb_events = lb_watch_events_map.get(m_key, [])
            all_candidate_events = []
            for ev in t_events:
                all_candidate_events.append(("trakt", ev))
            for ev in lb_events:
                all_candidate_events.append(("letterboxd", ev))

            existing_event_keys = {
                (we.provider, we.provider_event_id): we for we in existing_watch_events
            }

            has_new_events = False
            for prov_name, ev in all_candidate_events:
                ev_id = getattr(ev, "provider_event_id", None)
                if not ev_id:
                    ev_id = derive_event_id(prov_name, movie.id if movie else 0, ev.watched_at)

                if (prov_name, ev_id) not in existing_event_keys:
                    summary.new_watch_events += 1
                    has_new_events = True
                    if not dry_run and movie:
                        we_record = WatchEvent(
                            user_id=user_id,
                            movie_id=movie.id,
                            provider=prov_name,
                            provider_event_id=ev_id,
                            watched_at=ev.watched_at,
                        )
                        self.db.add(we_record)
                        existing_event_keys[(prov_name, ev_id)] = we_record

                        # If new event originated from Letterboxd and writing to Trakt is active:
                        if prov_name == "letterboxd" and write_to_trakt and trakt_snapshot:
                            c_hash = compute_semantic_hash(watched=True, rating=None, watch_events=[ev.watched_at])
                            w_idem_key = generate_idempotency_key(
                                user_id, movie.id, "letterboxd", "trakt", "create_watch", c_hash
                            )
                            chk_w = await self.db.execute(select(SyncEvent).where(SyncEvent.idempotency_key == w_idem_key))
                            existing_w_ev = chk_w.scalar_one_or_none()
                            if not existing_w_ev or existing_w_ev.status == "failed":
                                try:
                                    await self.trakt.mark_watched(user_id, p_movie, ev.watched_at)
                                    if existing_w_ev:
                                        existing_w_ev.status = "success"
                                        existing_w_ev.error_message = None
                                        existing_w_ev.new_state = json.dumps({"watched_at": ev.watched_at.isoformat()})
                                    else:
                                        s_ev = SyncEvent(
                                            user_id=user_id,
                                            movie_id=movie.id,
                                            source_provider="letterboxd",
                                            destination_provider="trakt",
                                            operation="create_watch",
                                            status="success",
                                            new_state=json.dumps({"watched_at": ev.watched_at.isoformat()}),
                                            content_hash=c_hash,
                                            idempotency_key=w_idem_key,
                                        )
                                        self.db.add(s_ev)
                                except Exception as ex:
                                    if existing_w_ev:
                                        existing_w_ev.error_message = str(ex)
                                    else:
                                        s_ev = SyncEvent(
                                            user_id=user_id,
                                            movie_id=movie.id,
                                            source_provider="letterboxd",
                                            destination_provider="trakt",
                                            operation="create_watch",
                                            status="failed",
                                            error_message=str(ex),
                                            content_hash=c_hash,
                                            idempotency_key=w_idem_key,
                                        )
                                        self.db.add(s_ev)

                        # If new event originated from Trakt, queue for Letterboxd export
                        if prov_name == "trakt":
                            await self.letterboxd.mark_watched(
                                user_id=user_id,
                                movie=p_movie,
                                watched_at=ev.watched_at,
                            )

            if not has_new_events and not res.has_conflict and (
                res.action_for_trakt == "none" and res.action_for_letterboxd == "none"
            ):
                summary.unchanged += 1

            # Update ProviderActivity snapshot with semantic hash
            if not dry_run and movie:
                # Trakt snapshot record
                if trakt_r is not None or t_events:
                    t_hash = compute_semantic_hash(
                        watched=len(t_events) > 0,
                        rating=trakt_r,
                        watch_events=[e.watched_at for e in t_events],
                    )
                    if not baseline_trakt:
                        baseline_trakt = ProviderActivity(
                            user_id=user_id,
                            movie_id=movie.id,
                            provider="trakt",
                            watched=len(t_events) > 0,
                            rating=trakt_r,
                            content_hash=t_hash,
                            last_seen_at=datetime.now(timezone.utc),
                        )
                        self.db.add(baseline_trakt)
                    else:
                        baseline_trakt.watched = len(t_events) > 0
                        baseline_trakt.rating = trakt_r
                        baseline_trakt.content_hash = t_hash
                        baseline_trakt.last_seen_at = datetime.now(timezone.utc)

                # Letterboxd snapshot record
                if lb_r is not None or lb_events:
                    lb_hash = compute_semantic_hash(
                        watched=len(lb_events) > 0,
                        rating=lb_r,
                        watch_events=[e.watched_at for e in lb_events],
                    )
                    if not baseline_lb:
                        baseline_lb = ProviderActivity(
                            user_id=user_id,
                            movie_id=movie.id,
                            provider="letterboxd",
                            watched=len(lb_events) > 0,
                            rating=lb_r,
                            content_hash=lb_hash,
                            last_seen_at=datetime.now(timezone.utc),
                        )
                        self.db.add(baseline_lb)
                    else:
                        baseline_lb.watched = len(lb_events) > 0
                        baseline_lb.rating = lb_r
                        baseline_lb.content_hash = lb_hash
                        baseline_lb.last_seen_at = datetime.now(timezone.utc)

        if not dry_run:
            await self.db.commit()

        return summary
