"""Scores eligible Circles out of 100 points.

Each Circle is scored on four questions.

    topic     (45)  Is it about something the member cares about?
    activity  (30)  Is it alive?
    join      (10)  Can they get in right away?
    attend    (15)  Can they actually attend?

The point values live in app.config. Every function here is pure, so the rubric can be unit
tested without a database.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app import config
from app.models import Personalization
from app.repository import Circle, Engagement, Leader, User
from app.timeutil import days_between

MatchKind = Literal["topic", "tag", "inferred_topic"]
AttendKind = Literal["virtual", "near", "unknown"]


@dataclass(frozen=True)
class InterestProfile:
    """What we know about a member's interests.

    `stated` holds the topics they picked themselves. `inferred` maps the main topic of each
    Circle they already belong to onto that Circle's name, so explanations can cite it.
    """

    stated: frozenset[str]
    inferred: dict[str, str]

    @property
    def topics(self) -> frozenset[str]:
        """Every topic worth retrieving Circles for, stated or inferred."""
        return self.stated | frozenset(self.inferred)

    @property
    def personalization(self) -> Personalization:
        # Reported in the API response so clients know how personal the list is.
        if self.stated:
            return "interests"
        if self.inferred:
            return "memberships"
        return "cold_start"


@dataclass(frozen=True)
class TopicMatch:
    """Which interest a Circle matched on. Used to word the explanation."""

    kind: MatchKind
    topic: str
    via_circle: str | None = None  # set for inferred matches only


@dataclass(frozen=True)
class AttendFit:
    """How reachable the Circle is for this member, plus the city for the explanation."""

    kind: AttendKind
    city: str | None = None


@dataclass(frozen=True)
class Points:
    topic: int
    activity: int
    join: int
    attend: int

    @property
    def total(self) -> int:
        return self.topic + self.activity + self.join + self.attend


@dataclass(frozen=True)
class ScoredCircle:
    """A Circle with its points and the facts that earned them."""

    circle: Circle
    points: Points
    match: TopicMatch | None
    attend: AttendFit
    leader: Leader | None


def build_profile(user: User, member_circles: Iterable[Circle]) -> InterestProfile:
    """Combine stated interests with topics borrowed from the member's current Circles.

    Inferred topics give members with no stated interests some personalization instead of
    falling straight to cold start. A stated interest always wins over an inferred one.
    """
    stated = frozenset(user.topic_interests)
    inferred: dict[str, str] = {}
    # Sort by id so the Circle named in the explanation is stable between runs.
    for circle in sorted(member_circles, key=lambda c: c.id):
        # Main topic only. Tags are too noisy to infer interests from.
        if circle.topic and circle.topic not in stated and circle.topic not in inferred:
            inferred[circle.topic] = circle.name
    return InterestProfile(stated=stated, inferred=inferred)


def topic_points(circle: Circle, profile: InterestProfile) -> tuple[int, TopicMatch | None]:
    """Score topical relevance, strongest match first.

    main topic in stated interests     45
    main topic in inferred interests   22 (half)
    a tag in stated interests          15
    otherwise                           0
    """
    if circle.topic in profile.stated:
        return config.TOPIC_MAIN_MATCH, TopicMatch("topic", circle.topic)
    if circle.topic in profile.inferred:
        points = int(config.TOPIC_MAIN_MATCH * config.INFERRED_INTEREST_FACTOR)
        return points, TopicMatch("inferred_topic", circle.topic, profile.inferred[circle.topic])
    # Tags are a loose mix of topics in this dataset and often leave out the Circle's own
    # topic, so a tag match is weak evidence and scores a third of a main topic match.
    for tag in circle.tags:
        if tag in profile.stated:
            return config.TOPIC_TAG_MATCH, TopicMatch("tag", tag)
    # Inferred interests are not matched against tags. Stacking two weak signals was mostly noise.
    return 0, None


def _tier(value: float, tiers: tuple[tuple[float, int], ...], *, at_most: bool = False) -> int:
    """Points for the first tier `value` reaches. Tiers are ordered best first.

    By default a tier is reached when value >= threshold. With at_most=True it is
    value <= threshold, used for days since last activity where lower is better.
    """
    for threshold, points in tiers:
        if (value <= threshold) if at_most else (value >= threshold):
            return points
    return 0


def activity_points(circle: Circle, engagement: Engagement | None, reference_time: datetime) -> int:
    """Score how alive the Circle is, up to 30.

    Four signals, so no single one dominates. Post volume, recency, chat volume, and how
    much members respond to posts. Tiers are used instead of linear scaling so the numbers
    are easy to explain, and "very active" means something concrete.
    """
    # Capped so a very large Circle can't win on volume alone.
    posts = min(circle.feed_posts_30d * config.POSTS_POINTS_EACH, config.POSTS_MAX)
    recency = _tier(days_between(reference_time, circle.last_activity_at), config.RECENCY_POINTS, at_most=True)
    chat = _tier(circle.chat_messages_30d, config.CHAT_POINTS)
    # Average per post, not total, so it measures quality rather than repeating the post count.
    reactions = _tier(engagement.avg_per_post if engagement else 0.0, config.ENGAGEMENT_POINTS)
    return posts + recency + chat + reactions


def join_points(circle: Circle) -> int:
    """Score how easy it is to get in, up to 10.

    An open Circle can be joined in one tap. A request Circle needs a leader to approve, which
    takes time and can be declined, so it scores a little lower. The gap is kept small on
    purpose so a request only Circle that is clearly the best match still ranks first.
    """
    return config.JOIN_POINTS[circle.join_policy]


def _city(location: str | None) -> str | None:
    """Normalize a location for comparison. Remote counts as unknown."""
    if not location or location.strip().lower() == "remote":
        return None
    return location.strip().lower()


def attend_points(circle: Circle, user: User, leader: Leader | None) -> tuple[int, AttendFit]:
    """Score how practical it is for the member to show up, up to 15.

    Virtual Circles are reachable from anywhere. For in person and hybrid Circles the format
    sets the base points, and a same city match adds a bonus.

    Circles have no location field, so the leader's city stands in for the Circle's. Since that
    is an assumption, it can only help. A different city is scored the same as an unknown one
    because the leader may not live where the Circle meets, and exact string matching can't
    tell a neighbouring town from the other side of the country.
    """
    if circle.format == "virtual":
        return config.ATTEND_VIRTUAL, AttendFit("virtual")

    leader_location = leader.location if leader else None
    user_city, circle_city = _city(user.location), _city(leader_location)
    near = user_city is not None and user_city == circle_city
    fit = AttendFit("near", leader_location) if near else AttendFit("unknown")

    if circle.format == "hybrid":
        # Hybrid Circles can be joined remotely, so they start close to virtual.
        return (config.ATTEND_HYBRID_SAME_CITY if near else config.ATTEND_HYBRID), fit
    return (config.ATTEND_IN_PERSON_SAME_CITY if near else config.ATTEND_IN_PERSON), fit


def score_circle(
    circle: Circle,
    *,
    user: User,
    profile: InterestProfile,
    leader: Leader | None,
    engagement: Engagement | None,
    reference_time: datetime,
) -> ScoredCircle:
    """Answer all four questions for one Circle and keep the facts behind each score."""
    topic, match = topic_points(circle, profile)
    attend, fit = attend_points(circle, user, leader)
    points = Points(
        topic=topic,
        activity=activity_points(circle, engagement, reference_time),
        join=join_points(circle),
        attend=attend,
    )
    return ScoredCircle(circle=circle, points=points, match=match, attend=fit, leader=leader)


def rank_key(scored: ScoredCircle) -> tuple[int, float, int]:
    """Sort key with the highest total first."""
    # Ties go to the more recently active Circle, then the lower id, which keeps output deterministic.
    return (-scored.points.total, -scored.circle.last_activity_at.timestamp(), scored.circle.id)
