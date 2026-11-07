"""The four planted scenarios from the assignment README."""


def get_recs(client, user_id, **params):
    response = client.get(f"/users/{user_id}/recommendations", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def circle_ids(body):
    return [r["circle"]["id"] for r in body["recommendations"]]


def excluded(body):
    return {e["id"]: e["reason"] for e in body["debug"]["excluded"]}


class TestColdStart:
    def test_still_gets_a_full_list(self, client):
        body = get_recs(client, 42)
        assert body["personalization"] == "cold_start"
        assert len(body["recommendations"]) == 5
        assert body.get("hint")

    def test_only_healthy_discoverable_circles(self, client):
        ids = circle_ids(get_recs(client, 42))
        assert not set(ids) & {18, 21, 30}  # unlisted
        assert 20 not in ids  # full
        assert 32 not in ids  # inactive

    def test_variety_of_topics(self, client):
        topics = [r["circle"]["topic"] for r in get_recs(client, 42)["recommendations"] if r["circle"]["topic"]]
        assert len(topics) == len(set(topics))


class TestObviousMatches:
    def test_top_two(self, client):
        body = get_recs(client, 7)
        assert body["personalization"] == "interests"
        assert set(circle_ids(body)[:2]) == {5, 6}

    def test_explanation_names_the_interest(self, client):
        recs = {r["circle"]["id"]: r for r in get_recs(client, 7)["recommendations"]}
        assert "Leadership skills" in recs[5]["explanation"]
        assert "Public speaking" in recs[6]["explanation"]

    def test_excludes_current_circle(self, client):
        assert 4 not in circle_ids(get_recs(client, 7))


class TestDuplicates:
    def test_only_one_negotiation_circle(self, client):
        ids = circle_ids(get_recs(client, 15))
        assert len(set(ids) & {10, 11, 12}) == 1

    def test_duplicates_collapsed_into_similar(self, client):
        body = get_recs(client, 15)
        winner = next(r for r in body["recommendations"] if r["circle"]["id"] in {10, 11, 12})
        similar = {s["id"] for s in winner["similar_circles"]}
        assert similar == {10, 11, 12} - {winner["circle"]["id"]}

    def test_second_interest_represented(self, client):
        assert 13 in circle_ids(get_recs(client, 15))

    def test_excludes_current_circles(self, client):
        assert not set(circle_ids(get_recs(client, 15))) & {9, 35}


class TestFullAndInactive:
    def test_healthy_alternative_ranks_first(self, client):
        assert circle_ids(get_recs(client, 23))[0] == 22

    def test_traps_do_not_rank(self, client):
        ids = circle_ids(get_recs(client, 23))
        assert 20 not in ids and 21 not in ids

    def test_exclusions_are_explained_in_debug(self, client):
        reasons = excluded(get_recs(client, 23, debug=True))
        assert reasons[20] == "full"
        assert reasons[21] in {"unlisted", "inactive"}  # it's both
        assert reasons[32] == "inactive"
        assert reasons[23] == "already_member"
