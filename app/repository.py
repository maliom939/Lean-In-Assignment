"""All SQL lives here. Functions take a connection and return frozen dataclasses.

Queries that take a set of ids pass it as one JSON array and expand it with json_each, so
they never hit SQLite's bound parameter limit no matter how many ids there are.
"""

import json
import sqlite3
from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app import config
from app.timeutil import format_ts, parse_ts


@dataclass(frozen=True)
class User:
    id: int
    first_name: str
    last_name: str
    has_photo: bool
    bio: str | None
    job_title: str | None
    company: str | None
    industry: str | None
    location: str | None
    joined_at: datetime
    profile_completeness: float
    topic_interests: tuple[str, ...]


@dataclass(frozen=True)
class Circle:
    id: int
    name: str
    slug: str
    description: str | None
    topic: str | None
    tags: tuple[str, ...]
    cover_image_url: str | None
    format: str
    access: str
    join_policy: str
    max_members: int | None
    member_count: int
    created_at: datetime
    last_activity_at: datetime
    feed_posts_30d: int
    chat_messages_30d: int

    @property
    def spots_left(self) -> int | None:
        """Open places, or None when the Circle is uncapped."""
        if self.max_members is None:
            return None
        return max(self.max_members - self.member_count, 0)

    @property
    def is_full(self) -> bool:
        return self.max_members is not None and self.member_count >= self.max_members


@dataclass(frozen=True)
class Leader:
    user_id: int
    first_name: str
    job_title: str | None
    location: str | None
    profile_completeness: float


@dataclass(frozen=True)
class Engagement:
    circle_id: int
    posts: int
    interactions: int  # reactions plus comments plus saves

    @property
    def avg_per_post(self) -> float:
        return self.interactions / self.posts if self.posts else 0.0


def _json_array(values: Iterable) -> str:
    return json.dumps(sorted(set(values)))


def get_reference_time(conn: sqlite3.Connection) -> datetime:
    """The point in time that activity and recency are measured from."""
    if config.REFERENCE_NOW is not None:
        return config.REFERENCE_NOW
    row = conn.execute("SELECT value FROM dataset_meta WHERE key = 'reference_time'").fetchone()
    if row is None:
        raise RuntimeError("dataset_meta.reference_time is missing. Re-run `python -m app.seed`.")
    return parse_ts(row["value"])


def get_user(conn: sqlite3.Connection, user_id: int) -> User | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    interests = tuple(
        r["topic_slug"]
        for r in conn.execute(
            "SELECT topic_slug FROM user_topic_interests WHERE user_id = ? ORDER BY topic_slug", (user_id,)
        )
    )
    return User(
        id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        has_photo=bool(row["has_photo"]),
        bio=row["bio"],
        job_title=row["job_title"],
        company=row["company"],
        industry=row["industry"],
        location=row["location"],
        joined_at=parse_ts(row["joined_at"]),
        profile_completeness=row["profile_completeness"],
        topic_interests=interests,
    )


def get_user_circle_ids(conn: sqlite3.Connection, user_id: int) -> set[int]:
    """Circles the member belongs to, in any role. Served by the memberships primary key."""
    rows = conn.execute("SELECT circle_id FROM memberships WHERE user_id = ?", (user_id,))
    return {r["circle_id"] for r in rows}


def get_candidate_circle_ids(
    conn: sqlite3.Connection,
    *,
    topics: Collection[str],
    tags: Collection[str],
    popular_limit: int = config.POPULAR_POOL_SIZE,
) -> set[int]:
    """Circles worth scoring for one member, without loading the whole catalog.

    Three sources are combined. Circles whose main topic is in `topics` (topic index),
    Circles carrying any of `tags` (tag index), and the most active public Circles with room
    (popularity index) so cold start members and short lists still get filled.
    Eligibility is not decided here. The recommender applies the hard filters afterwards.
    """
    rows = conn.execute(
        """SELECT id FROM circles
           WHERE topic_slug IN (SELECT value FROM json_each(:topics))
           UNION
           SELECT circle_id FROM circle_tags
           WHERE tag IN (SELECT value FROM json_each(:tags))
           UNION
           SELECT id FROM (
               SELECT id FROM circles
               WHERE access = 'public' AND (max_members IS NULL OR member_count < max_members)
               ORDER BY feed_posts_30d DESC, last_activity_at DESC
               LIMIT :popular_limit
           )""",
        {"topics": _json_array(topics), "tags": _json_array(tags), "popular_limit": popular_limit},
    )
    return {r[0] for r in rows}


def get_circles(conn: sqlite3.Connection, circle_ids: Collection[int]) -> list[Circle]:
    """Circles with the given ids, ordered by id. Unknown ids are ignored."""
    if not circle_ids:
        return []
    ids = _json_array(circle_ids)

    tags: dict[int, list[str]] = defaultdict(list)
    for r in conn.execute(
        """SELECT circle_id, tag FROM circle_tags
           WHERE circle_id IN (SELECT value FROM json_each(?))
           ORDER BY circle_id, tag""",
        (ids,),
    ):
        tags[r["circle_id"]].append(r["tag"])

    rows = conn.execute(
        "SELECT * FROM circles WHERE id IN (SELECT value FROM json_each(?)) ORDER BY id", (ids,)
    )
    return [
        Circle(
            id=r["id"],
            name=r["name"],
            slug=r["slug"],
            description=r["description"],
            topic=r["topic_slug"],
            tags=tuple(tags.get(r["id"], ())),
            cover_image_url=r["cover_image_url"],
            format=r["format"],
            access=r["access"],
            join_policy=r["join_policy"],
            max_members=r["max_members"],
            member_count=r["member_count"],
            created_at=parse_ts(r["created_at"]),
            last_activity_at=parse_ts(r["last_activity_at"]),
            feed_posts_30d=r["feed_posts_30d"],
            chat_messages_30d=r["chat_messages_30d"],
        )
        for r in rows
    ]


def get_all_circle_ids(conn: sqlite3.Connection) -> set[int]:
    """Every Circle id. For offline checks and tests, never on the request path."""
    return {r[0] for r in conn.execute("SELECT id FROM circles")}


def get_leaders(conn: sqlite3.Connection, circle_ids: Collection[int]) -> dict[int, list[Leader]]:
    """Leaders of the given Circles, earliest to join first. Uses the (circle_id, role) index."""
    if not circle_ids:
        return {}
    leaders: dict[int, list[Leader]] = defaultdict(list)
    rows = conn.execute(
        """SELECT m.circle_id, u.id, u.first_name, u.job_title, u.location, u.profile_completeness
           FROM memberships m JOIN users u ON u.id = m.user_id
           WHERE m.circle_id IN (SELECT value FROM json_each(?)) AND m.role = 'leader'
           ORDER BY m.circle_id, m.joined_at, u.id""",
        (_json_array(circle_ids),),
    )
    for r in rows:
        leaders[r["circle_id"]].append(
            Leader(
                user_id=r["id"],
                first_name=r["first_name"],
                job_title=r["job_title"],
                location=r["location"],
                profile_completeness=r["profile_completeness"],
            )
        )
    return dict(leaders)


def get_recent_engagement(
    conn: sqlite3.Connection,
    circle_ids: Collection[int],
    reference_time: datetime,
    days: int = config.ACTIVITY_WINDOW_DAYS,
) -> dict[int, Engagement]:
    """Post count and total interactions per Circle over the last `days` days.

    Circles with no posts in the window are absent from the result. Uses the
    (circle_id, created_at) index, so each Circle is one range scan.
    """
    if not circle_ids:
        return {}
    rows = conn.execute(
        """SELECT circle_id,
                  COUNT(*) AS posts,
                  SUM(reaction_count + comment_count + save_count) AS interactions
           FROM activity_posts
           WHERE circle_id IN (SELECT value FROM json_each(:ids))
             AND created_at >= :since AND created_at <= :until
           GROUP BY circle_id""",
        {
            "ids": _json_array(circle_ids),
            "since": format_ts(reference_time - timedelta(days=days)),
            "until": format_ts(reference_time),
        },
    )
    return {
        r["circle_id"]: Engagement(circle_id=r["circle_id"], posts=r["posts"], interactions=r["interactions"])
        for r in rows
    }


def get_topic_labels(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["slug"]: r["label"] for r in conn.execute("SELECT slug, label FROM topics")}


def ping(conn: sqlite3.Connection) -> None:
    """Raise if the database is unreachable or not seeded."""
    get_reference_time(conn)
