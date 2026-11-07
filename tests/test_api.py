import pytest


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_root_redirects_to_docs(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/docs"


def test_unknown_user_is_404(client):
    assert client.get("/users/999/recommendations").status_code == 404


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 21}, {"limit": "abc"}])
def test_invalid_limit_is_422(client, params):
    assert client.get("/users/7/recommendations", params=params).status_code == 422


def test_invalid_user_id_is_422(client):
    assert client.get("/users/0/recommendations").status_code == 422


def test_limit_is_respected(client):
    body = client.get("/users/7/recommendations", params={"limit": 3}).json()
    assert len(body["recommendations"]) == 3
    assert [r["rank"] for r in body["recommendations"]] == [1, 2, 3]


def test_meaningful_nulls_are_kept(client):
    recs = client.get("/users/42/recommendations", params={"limit": 20}).json()["recommendations"]
    for r in recs:
        assert {"topic", "max_members", "spots_left"} <= r["circle"].keys()
    assert any(r["circle"]["max_members"] is None for r in recs)


def test_debug_is_opt_in(client):
    plain = client.get("/users/7/recommendations").json()
    assert "debug" not in plain
    assert all("score" not in r for r in plain["recommendations"])

    debug = client.get("/users/7/recommendations", params={"debug": True}).json()
    assert "excluded" in debug["debug"]
    assert all("score" in r for r in debug["recommendations"])


def test_ready(client):
    assert client.get("/ready").json() == {"status": "ok"}


def test_request_id_is_echoed_or_generated(client):
    assert client.get("/health", headers={"X-Request-ID": "abc123"}).headers["X-Request-ID"] == "abc123"
    generated = client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"}).headers["X-Request-ID"]
    assert generated != "bad id\nwith newline" and len(generated) == 32
