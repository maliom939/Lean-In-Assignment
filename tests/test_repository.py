from datetime import datetime, timezone

from app import repository


def all_ids(conn):
    return repository.get_all_circle_ids(conn)


def test_reference_time(conn):
    assert repository.get_reference_time(conn) == datetime(2026, 9, 21, tzinfo=timezone.utc)


def test_get_user_with_interests(conn):
    user = repository.get_user(conn, 7)
    assert user.first_name == "Priya"
    assert set(user.topic_interests) == {"leadership-skills", "public-speaking"}
    assert user.location == "Seattle, WA"


def test_cold_start_user_is_empty(conn):
    user = repository.get_user(conn, 42)
    assert user.topic_interests == ()
    assert user.profile_completeness == 0
    assert repository.get_user_circle_ids(conn, 42) == set()


def test_unknown_user(conn):
    assert repository.get_user(conn, 999) is None


def test_user_circle_ids(conn):
    assert repository.get_user_circle_ids(conn, 15) == {9, 35}
    assert repository.get_user_circle_ids(conn, 7) == {4}


def test_circle_capacity_helpers(conn):
    circles = {c.id: c for c in repository.get_circles(conn, all_ids(conn))}
    assert len(circles) == 40
    assert circles[20].is_full and circles[20].spots_left == 0
    assert circles[1].max_members is None and circles[1].spots_left is None and not circles[1].is_full
    assert circles[22].spots_left == 6


def test_circle_topics_and_tags(conn):
    circles = {c.id: c for c in repository.get_circles(conn, all_ids(conn))}
    assert circles[27].topic is None and circles[27].tags == ()
    assert circles[17].tags.count("difficult-conversations") == 1


def test_get_circles_is_scoped(conn):
    assert [c.id for c in repository.get_circles(conn, {22, 5, 9999})] == [5, 22]
    assert repository.get_circles(conn, set()) == []


def test_leaders(conn):
    leaders = repository.get_leaders(conn, all_ids(conn))
    assert len(leaders) == 40
    assert leaders[5][0].first_name == "Ingrid"
    assert leaders[5][0].location == "Seattle, WA"
    assert repository.get_leaders(conn, {5}).keys() == {5}


def test_recent_engagement_window(conn):
    ref = repository.get_reference_time(conn)
    engagement = repository.get_recent_engagement(conn, all_ids(conn), ref)
    assert 21 not in engagement
    assert engagement[5].posts == 11
    assert engagement[5].avg_per_post > 10
    assert repository.get_recent_engagement(conn, {5}, ref).keys() == {5}


def test_topic_labels(conn):
    labels = repository.get_topic_labels(conn)
    assert len(labels) == 22
    assert labels["negotiation"] == "Negotiation"


class TestCandidates:
    def test_topic_matches_are_retrieved(self, conn):
        ids = repository.get_candidate_circle_ids(conn, topics={"negotiation"}, tags=set(), popular_limit=0)
        circles = repository.get_circles(conn, ids)
        assert {10, 11, 12} <= ids
        assert all(c.topic == "negotiation" for c in circles)

    def test_tag_matches_are_retrieved(self, conn):
        ids = repository.get_candidate_circle_ids(conn, topics=set(), tags={"negotiation"}, popular_limit=0)
        circles = repository.get_circles(conn, ids)
        assert ids and all("negotiation" in c.tags for c in circles)

    def test_popular_pool_is_public_with_room_and_ordered(self, conn):
        ids = repository.get_candidate_circle_ids(conn, topics=set(), tags=set(), popular_limit=5)
        circles = repository.get_circles(conn, ids)
        assert len(circles) == 5
        assert all(c.access == "public" and not c.is_full for c in circles)
        top_posts = sorted(
            (c.feed_posts_30d for c in repository.get_circles(conn, all_ids(conn)) if c.access == "public" and not c.is_full),
            reverse=True,
        )[:5]
        assert sorted((c.feed_posts_30d for c in circles), reverse=True) == top_posts

    def test_empty_profile_and_pool_returns_nothing(self, conn):
        assert repository.get_candidate_circle_ids(conn, topics=set(), tags=set(), popular_limit=0) == set()
