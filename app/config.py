"""Runtime settings and the scoring rubric.

Infrastructure settings come from environment variables. 
Ranking numbers are code, so a change to them goes through review and the tests.
"""

import os
from datetime import datetime
from pathlib import Path

from app.timeutil import parse_ts

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = Path(os.environ.get("RECS_DB_PATH", ROOT_DIR / "recs.db"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
API_VERSION = "1.0.0"


def _reference_now() -> datetime | None:
    value = os.environ.get("REFERENCE_NOW")
    if not value:
        return None
    try:
        return parse_ts(value)
    except ValueError as exc:
        raise RuntimeError(f"REFERENCE_NOW must be an ISO 8601 timestamp, got {value!r}") from exc


# The dataset is a frozen snapshot, so "now" defaults to its latest timestamp (stored at
# seed time) instead of the wall clock. A live deployment would set this to None and use UTC now.
REFERENCE_NOW = _reference_now()

DEFAULT_LIMIT = 5
MAX_LIMIT = 20

# Candidate retrieval. Circles matching the member's topics or tags are always scored, and
# this many of the most active public Circles are added so every list can be filled.
POPULAR_POOL_SIZE = 50

ACTIVITY_WINDOW_DAYS = 30
INACTIVE_AFTER_DAYS = 60

MAX_PER_TOPIC = 1

# Scoring rubric, 100 points total.

# Topic (max 45). Tags are noisy in this dataset, so a tag only match is worth much less.
TOPIC_MAIN_MATCH = 45
TOPIC_TAG_MATCH = 15
INFERRED_INTEREST_FACTOR = 0.5

# Activity (max 30)
POSTS_POINTS_EACH = 1
POSTS_MAX = 10
RECENCY_POINTS = ((7, 10), (30, 5))  # (days since last activity <=, points)
CHAT_POINTS = ((100, 5), (30, 3))  # (messages in 30 days >=, points)
ENGAGEMENT_POINTS = ((10, 5), (5, 3))  # (avg interactions per post >=, points)

# Join (max 10). A small nudge toward Circles a member can join right away.
JOIN_POINTS = {"open": 10, "request": 7}

# Attend (max 15). The format is real data and carries most of these points. 
# Circles have no location field, so the city match uses the leader's location as a stand in. Because that is
# a guess, a match only earns a bonus and a mismatch is treated the same as unknown.
ATTEND_VIRTUAL = 15
ATTEND_HYBRID = 12
ATTEND_HYBRID_SAME_CITY = 15
ATTEND_IN_PERSON = 8
ATTEND_IN_PERSON_SAME_CITY = 15

VERY_ACTIVE_POINTS = 20
FEW_SPOTS_LEFT = 3
MAX_REASONS_IN_EXPLANATION = 3

MAX_SCORE = (
    TOPIC_MAIN_MATCH
    + POSTS_MAX
    + RECENCY_POINTS[0][1]
    + CHAT_POINTS[0][1]
    + ENGAGEMENT_POINTS[0][1]
    + max(JOIN_POINTS.values())
    + max(ATTEND_VIRTUAL, ATTEND_HYBRID_SAME_CITY, ATTEND_IN_PERSON_SAME_CITY)
)
if MAX_SCORE != 100:
    raise RuntimeError(f"Scoring rubric must total 100 points, got {MAX_SCORE}")
