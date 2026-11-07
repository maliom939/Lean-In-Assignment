"""Load data/*.json into a fresh SQLite database.

Run it as a module from the repo root. Both the database path and the data folder can be
overridden on the command line.

The database is built in a temporary file next to the target and swapped in at the end, so a
running API never sees a half loaded database and a failed load leaves the old one intact.
"""

import argparse
import json
import logging
import os
import sqlite3
from pathlib import Path

from app import config, db
from app.timeutil import format_ts, parse_ts

logger = logging.getLogger(__name__)

TABLES = [
    "topics",
    "users",
    "user_topic_interests",
    "circles",
    "circle_tags",
    "memberships",
    "activity_posts",
]


def _load(data_dir: Path, name: str) -> list[dict]:
    return json.loads((data_dir / name).read_text(encoding="utf-8"))


def _populate(conn: sqlite3.Connection, data_dir: Path) -> None:
    topics = _load(data_dir, "topics.json")
    users = _load(data_dir, "users.json")
    circles = _load(data_dir, "circles.json")
    memberships = _load(data_dir, "memberships.json")
    activity = _load(data_dir, "activity.json")

    with conn:
        conn.executemany(
            "INSERT INTO topics (id, slug, label, domain) VALUES (:id, :slug, :label, :domain)",
            topics,
        )
        conn.executemany(
            """INSERT INTO users (id, first_name, last_name, has_photo, bio, job_title, company,
                                  industry, location, joined_at, profile_completeness)
               VALUES (:id, :first_name, :last_name, :has_photo, :bio, :job_title, :company,
                       :industry, :location, :joined_at, :profile_completeness)""",
            [{**u, "has_photo": int(u["has_photo"])} for u in users],
        )
        conn.executemany(
            "INSERT INTO user_topic_interests (user_id, topic_slug) VALUES (?, ?)",
            [(u["id"], slug) for u in users for slug in u["topic_interests"]],
        )
        conn.executemany(
            """INSERT INTO circles (id, name, slug, description, topic_slug, cover_image_url, format,
                                    access, join_policy, max_members, member_count, created_at,
                                    last_activity_at, feed_posts_30d, chat_messages_30d)
               VALUES (:id, :name, :slug, :description, :topic, :cover_image_url, :format,
                       :access, :join_policy, :max_members, :member_count, :created_at,
                       :last_activity_at, :feed_posts_30d, :chat_messages_30d)""",
            circles,
        )
        # The source data can repeat a tag on the same Circle, so tags are deduplicated in order.
        conn.executemany(
            "INSERT INTO circle_tags (circle_id, tag) VALUES (?, ?)",
            [(c["id"], tag) for c in circles for tag in dict.fromkeys(c["tags"])],
        )
        conn.executemany(
            """INSERT INTO memberships (user_id, circle_id, role, joined_at)
               VALUES (:user_id, :circle_id, :role, :joined_at)""",
            memberships,
        )
        conn.executemany(
            """INSERT INTO activity_posts (id, circle_id, author_user_id, body, reaction_count,
                                           comment_count, save_count, created_at)
               VALUES (:id, :circle_id, :author_user_id, :body, :reaction_count,
                       :comment_count, :save_count, :created_at)""",
            activity,
        )

        # The snapshot's "now" is its latest event, so recency is measured relative to the data.
        timestamps = [c["last_activity_at"] for c in circles] + [a["created_at"] for a in activity]
        reference_time = max(parse_ts(ts) for ts in timestamps)
        conn.execute(
            "INSERT INTO dataset_meta (key, value) VALUES ('reference_time', ?)",
            (format_ts(reference_time),),
        )

    problems = conn.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise RuntimeError(f"Foreign key violations after seeding: {[tuple(p) for p in problems]}")
    # Gives the query planner row counts so it picks the right indexes.
    conn.execute("ANALYZE")


def seed(db_path: Path, data_dir: Path = config.DATA_DIR) -> dict[str, int]:
    """Build the database at `db_path` from the JSON files in `data_dir`. Returns row counts."""
    db_path = Path(db_path)
    tmp_path = db_path.with_name(db_path.name + ".tmp")
    tmp_path.unlink(missing_ok=True)

    conn = db.connect(tmp_path)
    try:
        db.init_schema(conn)
        _populate(conn, data_dir)
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    except Exception:
        conn.close()
        tmp_path.unlink(missing_ok=True)
        raise
    conn.close()

    try:
        os.replace(tmp_path, db_path)
    except PermissionError as exc:
        tmp_path.unlink(missing_ok=True)
        # Windows refuses to replace a file another process has open.
        raise SystemExit(f"Cannot replace {db_path}. Is the API still running? ({exc})") from exc
    return counts


def main() -> None:
    logging.basicConfig(level=config.LOG_LEVEL, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Load the seed dataset into SQLite.")
    parser.add_argument("--db", type=Path, default=config.DB_PATH)
    parser.add_argument("--data", type=Path, default=config.DATA_DIR)
    args = parser.parse_args()

    counts = seed(args.db, args.data)
    logger.info("Seeded %s", args.db)
    for table, n in counts.items():
        logger.info("  %-22s%5d", table, n)


if __name__ == "__main__":
    main()
