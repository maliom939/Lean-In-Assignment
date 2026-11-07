from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app import config
from app.models import Reason
from app.recommender.diversify import diversify
from app.recommender.eligibility import exclusion_reason
from app.recommender.explain import build_explanation, build_reasons
from app.recommender.scoring import (
    activity_points,
    attend_points,
    build_profile,
    join_points,
    rank_key,
    score_circle,
    topic_points,
)
from app.repository import Circle, Engagement, Leader, User

NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)
LABELS = {"negotiation": "Negotiation", "confidence": "Confidence", "networking": "Networking"}


def make_circle(**overrides) -> Circle:
    base = Circle(
        id=1, name="Test Circle", slug="test-circle", description=None, topic="negotiation",
        tags=(), cover_image_url=None, format="virtual", access="public", join_policy="open",
        max_members=None, member_count=10, created_at=NOW - timedelta(days=300),
        last_activity_at=NOW - timedelta(days=1), feed_posts_30d=12, chat_messages_30d=150,
    )
    return replace(base, **overrides)


def make_user(**overrides) -> User:
    base = User(
        id=1, first_name="Test", last_name="User", has_photo=True, bio=None, job_title=None,
        company=None, industry=None, location="Seattle, WA", joined_at=NOW - timedelta(days=100),
        profile_completeness=0.6, topic_interests=("negotiation",),
    )
    return replace(base, **overrides)


def leader(location: str | None) -> Leader:
    return Leader(user_id=99, first_name="Lee", job_title="Founder", location=location, profile_completeness=1.0)


class TestEligibility:
    def test_eligible(self):
        assert exclusion_reason(make_circle(), set(), NOW) is None

    def test_already_member(self):
        assert exclusion_reason(make_circle(id=5), {5}, NOW) == "already_member"

    def test_unlisted(self):
        assert exclusion_reason(make_circle(access="unlisted"), set(), NOW) == "unlisted"

    def test_full(self):
        assert exclusion_reason(make_circle(max_members=10, member_count=10), set(), NOW) == "full"

    def test_uncapped_is_never_full(self):
        assert exclusion_reason(make_circle(max_members=None, member_count=500), set(), NOW) is None

    def test_inactive_needs_no_posts_and_long_silence(self):
        dead = make_circle(feed_posts_30d=0, last_activity_at=NOW - timedelta(days=61))
        assert exclusion_reason(dead, set(), NOW) == "inactive"

    def test_quiet_but_recent_is_not_inactive(self):
        quiet = make_circle(feed_posts_30d=0, last_activity_at=NOW - timedelta(days=20))
        assert exclusion_reason(quiet, set(), NOW) is None


class TestTopic:
    def test_main_topic_match(self):
        profile = build_profile(make_user(), [])
        points, match = topic_points(make_circle(topic="negotiation"), profile)
        assert points == config.TOPIC_MAIN_MATCH and match.kind == "topic"

    def test_tag_match_counts_much_less(self):
        profile = build_profile(make_user(), [])
        points, match = topic_points(make_circle(topic="confidence", tags=("negotiation",)), profile)
        assert points == config.TOPIC_TAG_MATCH and match.kind == "tag"

    def test_inferred_from_membership_is_half(self):
        user = make_user(topic_interests=())
        profile = build_profile(user, [make_circle(id=9, name="Seen & Heard", topic="networking")])
        points, match = topic_points(make_circle(topic="networking"), profile)
        assert points == config.TOPIC_MAIN_MATCH // 2
        assert match.kind == "inferred_topic" and match.via_circle == "Seen & Heard"

    def test_no_inferred_tag_matches(self):
        profile = build_profile(make_user(topic_interests=()), [make_circle(topic="networking")])
        assert topic_points(make_circle(topic="confidence", tags=("networking",)), profile) == (0, None)

    def test_null_topic_circle(self):
        profile = build_profile(make_user(), [])
        assert topic_points(make_circle(topic=None, tags=()), profile) == (0, None)

    @pytest.mark.parametrize(
        "interests, member_topics, expected",
        [(("negotiation",), [], "interests"), ((), ["networking"], "memberships"), ((), [], "cold_start")],
    )
    def test_personalization_mode(self, interests, member_topics, expected):
        circles = [make_circle(id=i, topic=t) for i, t in enumerate(member_topics)]
        assert build_profile(make_user(topic_interests=interests), circles).personalization == expected


class TestActivity:
    def test_max_is_30(self):
        busy = make_circle(feed_posts_30d=50, chat_messages_30d=500, last_activity_at=NOW)
        assert activity_points(busy, Engagement(1, posts=10, interactions=200), NOW) == 30

    def test_dead_is_zero(self):
        dead = make_circle(feed_posts_30d=0, chat_messages_30d=0, last_activity_at=NOW - timedelta(days=90))
        assert activity_points(dead, None, NOW) == 0

    def test_tiers(self):
        # 4 posts (4) + 20 days ago (5) + 35 chat (3) + avg engagement 6 (3)
        circle = make_circle(feed_posts_30d=4, chat_messages_30d=35, last_activity_at=NOW - timedelta(days=20))
        assert activity_points(circle, Engagement(1, posts=4, interactions=24), NOW) == 15


class TestJoinAndAttend:
    def test_join(self):
        assert join_points(make_circle(join_policy="open")) == 10
        assert join_points(make_circle(join_policy="request")) == 7

    @pytest.mark.parametrize(
        "fmt, user_loc, leader_loc, points, kind",
        [
            ("virtual", None, None, 15, "virtual"),
            ("hybrid", "Seattle, WA", "Seattle, WA", 15, "near"),
            ("hybrid", "Seattle, WA", "Boston, MA", 12, "unknown"),
            ("in_person", "Seattle, WA", "seattle, wa ", 15, "near"),
            ("in_person", "Seattle, WA", "Boston, MA", 8, "unknown"),
            ("in_person", None, "Boston, MA", 8, "unknown"),
            ("in_person", "Remote", "Boston, MA", 8, "unknown"),
            ("in_person", "Seattle, WA", None, 8, "unknown"),
        ],
    )
    def test_attend(self, fmt, user_loc, leader_loc, points, kind):
        got_points, fit = attend_points(make_circle(format=fmt), make_user(location=user_loc), leader(leader_loc))
        assert (got_points, fit.kind) == (points, kind)


def test_perfect_score_is_100():
    circle = make_circle(format="hybrid", feed_posts_30d=15, chat_messages_30d=200, last_activity_at=NOW)
    scored = score_circle(
        circle, user=make_user(), profile=build_profile(make_user(), []), leader=leader("Seattle, WA"),
        engagement=Engagement(1, posts=15, interactions=300), reference_time=NOW,
    )
    assert scored.points.total == 100


def _scored(circle: Circle, user: User | None = None):
    user = user or make_user()
    return score_circle(
        circle, user=user, profile=build_profile(user, []), leader=leader(None),
        engagement=None, reference_time=NOW,
    )


class TestDiversify:
    def test_one_per_topic_rest_become_similar(self):
        ranked = sorted(
            [
                _scored(make_circle(id=10, feed_posts_30d=6)),  # below the post points cap
                _scored(make_circle(id=11, feed_posts_30d=9)),
                _scored(make_circle(id=12, feed_posts_30d=8)),
                _scored(make_circle(id=13, topic="confidence")),
            ],
            key=rank_key,
        )
        picks = diversify(ranked, limit=5)
        assert [p.scored.circle.id for p in picks] == [11, 13]
        assert [s.circle.id for s in picks[0].similar] == [12, 10]

    def test_null_topic_circles_are_not_duplicates(self):
        ranked = [_scored(make_circle(id=27, topic=None)), _scored(make_circle(id=28, topic=None))]
        assert [p.scored.circle.id for p in diversify(ranked, limit=5)] == [27, 28]

    def test_limit(self):
        ranked = [_scored(make_circle(id=i, topic=f"t{i}")) for i in range(10)]
        assert len(diversify(ranked, limit=3)) == 3

    @pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 5, "max_per_topic": 0}])
    def test_rejects_bad_arguments(self, kwargs):
        with pytest.raises(ValueError):
            diversify([], **kwargs)


class TestExplain:
    def test_topic_match_sentence(self):
        reasons = build_reasons(_scored(make_circle()), LABELS, cold_start=False)
        assert reasons[0] == Reason(code="topic_match", text="Matches your interest in Negotiation")

    def test_tag_match_is_worded_softly(self):
        scored = _scored(make_circle(topic="confidence", tags=("negotiation",)))
        assert build_reasons(scored, LABELS, cold_start=False)[0].text.startswith("Tagged Negotiation")

    def test_cold_start_popular(self):
        user = make_user(topic_interests=(), location=None)
        reasons = build_reasons(_scored(make_circle(), user), LABELS, cold_start=True)
        assert reasons[0].code == "popular" and "Negotiation" in reasons[0].text

    def test_near_you_credits_the_leader_city(self):
        user = make_user(location="Seattle, WA")
        scored = score_circle(
            make_circle(format="in_person"), user=user, profile=build_profile(user, []),
            leader=leader("Seattle, WA"), engagement=None, reference_time=NOW,
        )
        near = next(r for r in build_reasons(scored, LABELS, cold_start=False) if r.code == "near_you")
        assert near.text == "Its leader is based in Seattle, WA, like you"

    def test_other_city_gets_no_location_reason(self):
        user = make_user(location="Seattle, WA")
        scored = score_circle(
            make_circle(format="in_person"), user=user, profile=build_profile(user, []),
            leader=leader("Boston, MA"), engagement=None, reference_time=NOW,
        )
        codes = {r.code for r in build_reasons(scored, LABELS, cold_start=False)}
        assert not codes & {"near_you", "virtual"}

    def test_few_spots_left_is_mentioned(self):
        scored = _scored(make_circle(max_members=12, member_count=10))
        assert "Only 2 spots left." in build_explanation(build_reasons(scored, LABELS, cold_start=False))

    def test_explanation_is_short_and_hides_score(self):
        scored = _scored(make_circle())
        text = build_explanation(build_reasons(scored, LABELS, cold_start=False))
        assert text.count(".") <= config.MAX_REASONS_IN_EXPLANATION
        assert str(scored.points.total) not in text
