"""SQLite connection helpers."""

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
BUSY_TIMEOUT_SECONDS = 5.0


def connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a connection with rows addressable by column name and foreign keys enforced.

    Read only connections use SQLite's URI mode so the API can never write to the database.
    """
    path = Path(path)
    # FastAPI may run a sync dependency and its route on different threadpool workers, so the
    # same thread check is turned off. Connections are still one per request and never shared.
    if read_only:
        conn = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=BUSY_TIMEOUT_SECONDS,
            check_same_thread=False,
        )
    else:
        conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
