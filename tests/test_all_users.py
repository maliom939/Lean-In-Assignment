from datetime import timedelta

import pytest

from app import config
from app.timeutil import parse_ts

REFERENCE = parse_ts("2026-09-21T00:00:00Z")


# Computed from the raw JSON rather than the recommender's own code.
@pytest.fixture(scope="module")
def never_recommendable(raw):
    bad = set()
    for c in raw["circles"]:
        stale = REFERENCE - parse_ts(c["last_activity_at"]) > timedelta(days=config.INACTIVE_AFTER_DAYS)
        full = c["max_members"] is not None and c["member_count"] >= c["max_members"]
        if c["access"] == "unlisted" or full or (c["feed_posts_30d"] == 0 and stale):
            bad.add(c["id"])
    return bad


@pytest.fixture(scope="module")
def memberships_by_user(raw):
    out: dict[int, set[int]] = {}
    for m in raw["memberships"]:
        out.setdefault(m["user_id"], set()).add(m["circle_id"])
    return out


@pytest.mark.parametrize("user_id", range(1, 101))
def test_user_gets_valid_recommendations(client, user_id, never_recommendable, memberships_by_user):
    response = client.get(f"/users/{user_id}/recommendations")
    assert response.status_code == 200
    recs = response.json()["recommendations"]

    assert len(recs) == config.DEFAULT_LIMIT
    assert [r["rank"] for r in recs] == list(range(1, len(recs) + 1))

    ids = [r["circle"]["id"] for r in recs]
    assert len(ids) == len(set(ids))
    assert not set(ids) & memberships_by_user.get(user_id, set())
    assert not set(ids) & never_recommendable

    topics = [r["circle"]["topic"] for r in recs if r["circle"]["topic"]]
    assert len(topics) == len(set(topics))

    similar = {s["id"] for r in recs for s in r["similar_circles"]}
    assert not similar & set(ids)

    for r in recs:
        assert r["explanation"].strip()
        assert r["reasons"]
