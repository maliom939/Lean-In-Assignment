"""Print recommendations for the four planted scenarios, with scores and exclusions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db  # noqa: E402
from app.recommender import recommend  # noqa: E402

SCENARIOS = [
    (42, "Cold start"),
    (7, "Obvious matches (expect #5, #6)"),
    (15, "Duplicate Circles (expect one of #10/#11/#12)"),
    (23, "Full / inactive (expect #22, not #20/#21)"),
]


def main() -> int:
    if not config.DB_PATH.exists():
        print(f"No database at {config.DB_PATH}. Run `python -m app.seed` first.")
        return 1

    conn = db.connect(config.DB_PATH, read_only=True)
    try:
        for user_id, title in SCENARIOS:
            result = recommend(conn, user_id=user_id, limit=config.DEFAULT_LIMIT, debug=True)
            print(f"\n=== User {user_id}: {title}  [{result.personalization}]")
            for rec in result.recommendations:
                c = rec.circle
                similar = f"  (+{len(rec.similar_circles)} similar)" if rec.similar_circles else ""
                print(f"  {rec.rank}. #{c.id:<3} {c.name:<26} {c.topic or '-':<24} {rec.score.total:>3}{similar}")
                print(f"       {rec.explanation}")
            if result.hint:
                print(f"  hint: {result.hint}")
            skipped = ", ".join(f"#{e.id} {e.reason}" for e in result.debug.excluded)
            print(f"  excluded: {skipped}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
