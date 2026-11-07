"""Topic diversity for the final list.

Several near identical Circles on one topic would otherwise fill the list with the same
option. We treat a shared main topic as a duplicate. The best one is shown and the others are
attached to it, so the client can still offer them.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from app import config
from app.recommender.scoring import ScoredCircle


@dataclass
class Pick:
    """A Circle that made the list, plus the same topic Circles folded under it."""

    scored: ScoredCircle
    similar: list[ScoredCircle] = field(default_factory=list)


def topic_key(scored: ScoredCircle) -> str:
    """Grouping key for duplicate detection."""
    # Circles without a topic aren't duplicates of each other, so each one gets its own group.
    circle = scored.circle
    return circle.topic or f"circle:{circle.id}"


def diversify(
    ranked: Iterable[ScoredCircle], limit: int, max_per_topic: int = config.MAX_PER_TOPIC
) -> list[Pick]:
    """Keep the best Circles per topic. Same topic runners up become `similar` on the winner.

    `ranked` must be sorted best first, so the first Circle seen for a topic is its best.
    """
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    if max_per_topic < 1:
        raise ValueError(f"max_per_topic must be at least 1, got {max_per_topic}")

    picks: list[Pick] = []
    by_topic: dict[str, list[Pick]] = {}
    for scored in ranked:
        group = by_topic.setdefault(topic_key(scored), [])
        if len(group) < max_per_topic and len(picks) < limit:
            pick = Pick(scored)
            picks.append(pick)
            group.append(pick)
        elif group:
            # Keep walking after the list is full so every pick gets all of its alternatives.
            group[0].similar.append(scored)
    return picks
