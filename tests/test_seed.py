import pytest

from app.seed import seed


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_row_counts_match_json(conn, raw):
    assert count(conn, "topics") == len(raw["topics"])
    assert count(conn, "users") == len(raw["users"])
    assert count(conn, "circles") == len(raw["circles"])
    assert count(conn, "memberships") == len(raw["memberships"])
    assert count(conn, "activity_posts") == len(raw["activity"])
    assert count(conn, "user_topic_interests") == sum(len(u["topic_interests"]) for u in raw["users"])


def test_circle_tags_are_deduplicated(conn, raw):
    expected = sum(len(set(c["tags"])) for c in raw["circles"])
    assert count(conn, "circle_tags") == expected


def test_foreign_keys_hold(conn):
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_reference_time_is_dataset_snapshot(conn):
    value = conn.execute("SELECT value FROM dataset_meta WHERE key = 'reference_time'").fetchone()[0]
    assert value == "2026-09-21T00:00:00.000Z"


def test_null_topic_circles_preserved(conn):
    rows = conn.execute("SELECT id FROM circles WHERE topic_slug IS NULL ORDER BY id").fetchall()
    assert [r[0] for r in rows] == [27, 28]


def test_reseed_replaces_atomically(tmp_path):
    path = tmp_path / "recs.db"
    first = seed(path)
    assert seed(path) == first
    assert not (tmp_path / "recs.db.tmp").exists()


def test_failed_seed_keeps_previous_database(tmp_path):
    path = tmp_path / "recs.db"
    seed(path)
    before = path.read_bytes()
    with pytest.raises(FileNotFoundError):
        seed(path, data_dir=tmp_path / "missing")
    assert path.read_bytes() == before
    assert not (tmp_path / "recs.db.tmp").exists()


def test_popularity_index_is_used(conn):
    plan = conn.execute(
        """EXPLAIN QUERY PLAN
           SELECT id FROM circles WHERE access = 'public'
           ORDER BY feed_posts_30d DESC, last_activity_at DESC LIMIT 10"""
    ).fetchall()
    assert any("idx_circles_popular" in row[-1] for row in plan)
