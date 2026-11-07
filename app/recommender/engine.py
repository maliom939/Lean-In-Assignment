"""Wires the pipeline together and builds the API response.

`rank` holds the algorithm and takes plain objects, so tests can call it without a database.
`recommend` loads data through app.repository, calls `rank`, and maps the result onto the
Pydantic response models.
"""

import logging
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app import config, repository
from app.models import (
    CircleSummary,
    DebugInfo,
    ExcludedCircle,
    LeaderSummary,
    Recommendation,
    RecommendationResponse,
    ScoreBreakdown,
    SimilarCircle,
)
from app.recommender.diversify import Pick, diversify
from app.recommender.eligibility import exclusion_reason
from app.recommender.explain import build_explanation, build_reasons, hint_for, topic_label
from app.recommender.scoring import InterestProfile, build_profile, rank_key, score_circle
from app.repository import Circle, Engagement, Leader, User

logger = logging.getLogger(__name__)


class UserNotFoundError(LookupError):
    """Raised when recommendations are requested for a user that doesn't exist."""

    def __init__(self, user_id: int) -> None:
        super().__init__(f"User {user_id} not found")
        self.user_id = user_id


@dataclass(frozen=True)
class RankResult:
    picks: list[Pick]
    excluded: list[ExcludedCircle]
    candidates_scored: int


def rank(
    *,
    user: User,
    profile: InterestProfile,
    candidates: Iterable[Circle],
    member_circle_ids: set[int],
    leaders: dict[int, list[Leader]],
    engagement: dict[int, Engagement],
    reference_time: datetime,
    limit: int,
) -> RankResult:
    """Filter, score, sort and diversify candidate Circles for one member."""
    eligible: list[Circle] = []
    excluded: list[ExcludedCircle] = []
    for circle in candidates:
        reason = exclusion_reason(circle, member_circle_ids, reference_time)
        if reason:
            excluded.append(ExcludedCircle(id=circle.id, name=circle.name, reason=reason))
        else:
            eligible.append(circle)

    scored = sorted(
        (
            score_circle(
                c,
                user=user,
                profile=profile,
                # Most Circles have one leader. When there are several, the earliest to join is used.
                leader=(leaders.get(c.id) or [None])[0],
                engagement=engagement.get(c.id),
                reference_time=reference_time,
            )
            for c in eligible
        ),
        key=rank_key,
    )
    excluded.sort(key=lambda e: e.id)
    return RankResult(picks=diversify(scored, limit), excluded=excluded, candidates_scored=len(scored))


def _to_recommendation(
    rank_no: int, pick: Pick, labels: dict[str, str], *, cold_start: bool, debug: bool
) -> Recommendation:
    """Map one Pick onto the response model."""
    scored = pick.scored
    circle, points, leader = scored.circle, scored.points, scored.leader
    reasons = build_reasons(scored, labels, cold_start=cold_start)

    # Optional fields are only set when present, because the route serializes with exclude_unset.
    optional = {}
    if debug:
        optional["score"] = ScoreBreakdown(
            topic=points.topic,
            activity=points.activity,
            join=points.join,
            attend=points.attend,
            total=points.total,
        )

    return Recommendation(
        rank=rank_no,
        circle=CircleSummary(
            id=circle.id,
            name=circle.name,
            topic=circle.topic,
            topic_label=topic_label(circle.topic, labels) if circle.topic else None,
            format=circle.format,
            join_policy=circle.join_policy,
            member_count=circle.member_count,
            max_members=circle.max_members,
            spots_left=circle.spots_left,
        ),
        explanation=build_explanation(reasons),
        reasons=reasons,
        # First name and job title only. Enough to put a face on the Circle without
        # exposing the leader's full profile.
        leader=LeaderSummary(first_name=leader.first_name, job_title=leader.job_title) if leader else None,
        similar_circles=[SimilarCircle(id=s.circle.id, name=s.circle.name) for s in pick.similar],
        **optional,
    )


def recommend(
    conn: sqlite3.Connection, *, user_id: int, limit: int = config.DEFAULT_LIMIT, debug: bool = False
) -> RecommendationResponse:
    """Recommend Circles for `user_id`.

    Raises UserNotFoundError for an unknown user and ValueError for a limit out of range.
    With debug on, `excluded` lists the retrieved candidates that failed a hard filter.
    """
    if not 1 <= limit <= config.MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {config.MAX_LIMIT}, got {limit}")

    user = repository.get_user(conn, user_id)
    if user is None:
        raise UserNotFoundError(user_id)
    reference_time = repository.get_reference_time(conn)

    member_circle_ids = repository.get_user_circle_ids(conn, user_id)
    profile = build_profile(user, repository.get_circles(conn, member_circle_ids))

    # Only a shortlist is loaded and scored. Circles on the member's topics or tags come from
    # the topic and tag indexes, and a popularity pool tops it up so the list can always be filled.
    candidate_ids = repository.get_candidate_circle_ids(conn, topics=profile.topics, tags=profile.stated)
    candidates = repository.get_circles(conn, candidate_ids)

    result = rank(
        user=user,
        profile=profile,
        candidates=candidates,
        member_circle_ids=member_circle_ids,
        leaders=repository.get_leaders(conn, candidate_ids),
        engagement=repository.get_recent_engagement(conn, candidate_ids, reference_time),
        reference_time=reference_time,
        limit=limit,
    )

    personalization = profile.personalization
    logger.debug(
        "recommendations computed",
        extra={
            "user_id": user_id,
            "personalization": personalization,
            "candidates": len(candidate_ids),
            "scored": result.candidates_scored,
            "returned": len(result.picks),
        },
    )

    labels = repository.get_topic_labels(conn)
    cold_start = personalization == "cold_start"

    optional = {}
    if hint := hint_for(personalization):
        optional["hint"] = hint
    if debug:
        optional["debug"] = DebugInfo(excluded=result.excluded)

    return RecommendationResponse(
        user_id=user_id,
        reference_time=reference_time,
        personalization=personalization,
        recommendations=[
            _to_recommendation(i, pick, labels, cold_start=cold_start, debug=debug)
            for i, pick in enumerate(result.picks, start=1)
        ],
        **optional,
    )
