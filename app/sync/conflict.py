"""Three-way state comparison and conflict detection / resolution module.

Implements deterministic conflict detection across:
- Baseline (previously synchronized state for each provider)
- Trakt (current state)
- Letterboxd (current imported state)
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.sync.rating_scale import ratings_are_equivalent


@dataclass
class ConflictResolutionResult:
    has_conflict: bool
    field: Optional[str] = None
    trakt_value: Optional[float] = None
    letterboxd_value: Optional[float] = None
    previous_value: Optional[float] = None
    resolved_value: Optional[float] = None
    action_for_trakt: Optional[str] = None  # 'update_rating', 'none'
    action_for_letterboxd: Optional[str] = None  # 'export_rating', 'none'
    reason: str = ""


def compare_ratings_three_way(
    previous_rating: Optional[float] = None,
    trakt_rating: Optional[float] = None,
    letterboxd_rating: Optional[float] = None,
    trakt_baseline: Optional[float] = None,
    letterboxd_baseline: Optional[float] = None,
    trakt_updated_at: Optional[datetime] = None,
    letterboxd_updated_at: Optional[datetime] = None,
) -> ConflictResolutionResult:
    """Compare ratings across previous baseline, Trakt, and Letterboxd.
    
    All ratings MUST already be in the canonical Letterboxd scale (0.5 to 5.0).
    """
    t_base = trakt_baseline if trakt_baseline is not None else previous_rating
    lb_base = letterboxd_baseline if letterboxd_baseline is not None else previous_rating

    # 1. Both identical or equivalent -> No conflict, no change needed
    if ratings_are_equivalent(trakt_rating, letterboxd_rating):
        return ConflictResolutionResult(
            has_conflict=False,
            resolved_value=trakt_rating if trakt_rating is not None else letterboxd_rating,
            action_for_trakt="none",
            action_for_letterboxd="none",
            reason="Trakt and Letterboxd ratings are equivalent",
        )

    # 2. Trakt is unrated (None), Letterboxd has a rating
    if trakt_rating is None and letterboxd_rating is not None:
        if t_base is not None and not ratings_are_equivalent(t_base, trakt_rating):
            # User previously had rating on Trakt and explicitly deleted it on Trakt
            return ConflictResolutionResult(
                has_conflict=False,
                resolved_value=letterboxd_rating,
                action_for_trakt="none",
                action_for_letterboxd="none",
                reason="Rating removed on Trakt; Letterboxd rating preserved without deletion",
            )
        # Letterboxd has rating that Trakt does not have yet -> sync to Trakt
        return ConflictResolutionResult(
            has_conflict=False,
            resolved_value=letterboxd_rating,
            action_for_trakt="update_rating",
            action_for_letterboxd="none",
            reason="Letterboxd rating present; syncing to Trakt",
        )

    # 3. Letterboxd is unrated (None), Trakt has a rating
    if letterboxd_rating is None and trakt_rating is not None:
        if lb_base is not None and not ratings_are_equivalent(lb_base, letterboxd_rating):
            return ConflictResolutionResult(
                has_conflict=False,
                resolved_value=trakt_rating,
                action_for_trakt="none",
                action_for_letterboxd="none",
                reason="Rating removed on Letterboxd; Trakt preserved",
            )
        # Trakt has rating that Letterboxd lacks -> queue for Letterboxd export
        return ConflictResolutionResult(
            has_conflict=False,
            resolved_value=trakt_rating,
            action_for_trakt="none",
            action_for_letterboxd="export_rating",
            reason="Trakt rating present; queueing for Letterboxd export",
        )

    # 4. Both have ratings. Compare against their respective baselines
    trakt_changed = not ratings_are_equivalent(trakt_rating, t_base)
    letterboxd_changed = not ratings_are_equivalent(letterboxd_rating, lb_base)

    if trakt_changed and not letterboxd_changed:
        # Trakt changed, Letterboxd remained at baseline -> Propagate Trakt change to Letterboxd
        return ConflictResolutionResult(
            has_conflict=False,
            resolved_value=trakt_rating,
            action_for_trakt="none",
            action_for_letterboxd="export_rating",
            reason="Trakt rating was updated by user; queueing for Letterboxd export",
        )

    if letterboxd_changed and not trakt_changed:
        # Letterboxd changed, Trakt remained at baseline -> Propagate Letterboxd change to Trakt
        return ConflictResolutionResult(
            has_conflict=False,
            resolved_value=letterboxd_rating,
            action_for_trakt="update_rating",
            action_for_letterboxd="none",
            reason="Letterboxd rating was updated in import; syncing to Trakt",
        )

    # 5. Both changed to different non-equivalent values!
    # Check timestamps if available and unambiguous
    if (
        trakt_updated_at
        and letterboxd_updated_at
        and abs((trakt_updated_at - letterboxd_updated_at).total_seconds()) > 60
    ):
        if trakt_updated_at > letterboxd_updated_at:
            return ConflictResolutionResult(
                has_conflict=False,
                resolved_value=trakt_rating,
                action_for_trakt="none",
                action_for_letterboxd="export_rating",
                reason="Both changed; Trakt timestamp is newer",
            )
        else:
            return ConflictResolutionResult(
                has_conflict=False,
                resolved_value=letterboxd_rating,
                action_for_trakt="update_rating",
                action_for_letterboxd="none",
                reason="Both changed; Letterboxd timestamp is newer",
            )

    # 6. Genuine conflict -> Must not overwrite; flag for user review
    return ConflictResolutionResult(
        has_conflict=True,
        field="rating",
        trakt_value=trakt_rating,
        letterboxd_value=letterboxd_rating,
        previous_value=t_base or lb_base,
        resolved_value=None,
        action_for_trakt="none",
        action_for_letterboxd="none",
        reason="Conflicting ratings with no authoritative timestamp resolution",
    )
