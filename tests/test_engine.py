import pytest

from app import config, repository
from app.recommender import UserNotFoundError, rank, recommend
from app.recommender.scoring import build_profile


def _rank_everything(conn, user_id, limit):
    """Score the whole catalog with no retrieval step, as a reference answer."""
    user = repository.get_user(conn, user_id)
    member_ids = repository.get_user_circle_ids(conn, user_id)
    all_ids = repository.get_all_circle_ids(conn)
    reference_time = repository.get_reference_time(conn)
    result = rank(
        user=user,
        profile=build_profile(user, repository.get_circles(conn, member_ids)),
        candidates=repository.get_circles(conn, all_ids),
        member_circle_ids=member_ids,
        leaders=repository.get_leaders(conn, all_ids),
        engagement=repository.get_recent_engagement(conn, all_ids, reference_time),
        reference_time=reference_time,
        limit=limit,
    )
    return [(p.scored.circle.id, [s.circle.id for s in p.similar]) for p in result.picks]


@pytest.mark.parametrize("user_id", range(1, 101))
def test_retrieval_loses_nothing_compared_to_a_full_scan(conn, user_id):
    response = recommend(conn, user_id=user_id, limit=config.DEFAULT_LIMIT)
    got = [(r.circle.id, [s.id for s in r.similar_circles]) for r in response.recommendations]
    assert got == _rank_everything(conn, user_id, config.DEFAULT_LIMIT)


def test_unknown_user_raises(conn):
    with pytest.raises(UserNotFoundError):
        recommend(conn, user_id=999)


@pytest.mark.parametrize("limit", [0, config.MAX_LIMIT + 1])
def test_limit_out_of_range_raises(conn, limit):
    with pytest.raises(ValueError):
        recommend(conn, user_id=7, limit=limit)
