"""Hard filters applied before scoring.

A Circle that fails any of these is never recommended, no matter how well it matches.
This module is the single source of truth for eligibility. Candidate retrieval may skip
obviously ineligible Circles for speed, but every Circle is checked here before it is scored.
"""

from datetime import datetime

from app import config
from app.models import ExclusionReason
from app.repository import Circle
from app.timeutil import days_between


def is_inactive(circle: Circle, reference_time: datetime) -> bool:
    """True when the Circle has gone quiet, meaning no feed posts in 30 days and nothing at all for 60.

    Both conditions are required. A Circle with no posts but a recent chat or event is quiet,
    not dead, and should still be shown.
    """
    idle_days = days_between(reference_time, circle.last_activity_at)
    return circle.feed_posts_30d == 0 and idle_days > config.INACTIVE_AFTER_DAYS


def exclusion_reason(
    circle: Circle, member_circle_ids: set[int], reference_time: datetime
) -> ExclusionReason | None:
    """Why a Circle can't be recommended to this member, or None when it is eligible.

    Checks run in order and the first failure wins, so a Circle that is both unlisted and
    inactive is reported as unlisted.
    """
    if circle.id in member_circle_ids:
        return "already_member"
    # Unlisted Circles are reachable by direct link only, so they are never suggested.
    if circle.access != "public":
        return "unlisted"
    # A null max_members means uncapped, which is_full already handles.
    if circle.is_full:
        return "full"
    if is_inactive(circle, reference_time):
        return "inactive"
    # Request to join is deliberately not a filter. It only costs a few points in scoring.
    return None
