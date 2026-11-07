"""Circle recommender.

The pipeline runs in five stages.

    retrieval       repository.get_candidate_circle_ids picks a shortlist using indexes
    eligibility.py  drops Circles that can't be recommended (joined, unlisted, full, inactive)
    scoring.py      scores the rest out of 100 points (topic, activity, join, attend)
    diversify.py    keeps one Circle per topic and folds near duplicates into similar_circles
    explain.py      turns the points into member facing reasons

engine.py wires them together. All weights and thresholds live in app/config.py.
"""

from app.recommender.engine import UserNotFoundError, rank, recommend

__all__ = ["UserNotFoundError", "rank", "recommend"]
