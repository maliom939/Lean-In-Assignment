"""Member facing explanations.

Every reason is built from a fact that actually earned points, so the explanation is never
more confident than the data. Scores and internal terms are never shown to members.
"""

from app import config
from app.models import Reason, ReasonCode
from app.recommender.scoring import ScoredCircle

# Only one logistics reason makes it into the explanation, picked in this order. Scarcity and
# proximity are the most useful to know, and open to join is the least surprising.
LOGISTICS_PRIORITY: tuple[ReasonCode, ...] = (
    "spots_left",
    "near_you",
    "request_to_join",
    "virtual",
    "open_to_join",
)


def topic_label(slug: str, labels: dict[str, str]) -> str:
    """Display name for a topic slug."""
    # Tags are free text in the product, so a tag may not be in the taxonomy.
    return labels.get(slug) or slug.replace("-", " ").capitalize()


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def build_reasons(scored: ScoredCircle, labels: dict[str, str], *, cold_start: bool) -> list[Reason]:
    """All reasons for one Circle, most important first.

    The order is why this topic, then how active it is, then logistics such as spots,
    location and join policy. The full list goes in `reasons`, and build_explanation picks a
    short subset from it.
    """
    circle, match = scored.circle, scored.match
    very_active = scored.points.activity >= config.VERY_ACTIVE_POINTS
    posts = _plural(circle.feed_posts_30d, "post")
    reasons: list[Reason] = []

    # 1. Topic
    if match:
        label = topic_label(match.topic, labels)
        if match.kind == "topic":
            reasons.append(Reason(code="topic_match", text=f"Matches your interest in {label}"))
        elif match.kind == "tag":
            # Worded as tagged on purpose, because tags don't reliably describe what a Circle covers.
            reasons.append(Reason(code="tag_match", text=f"Tagged {label}, one of your interests"))
        else:
            # Name the member's own Circle so it's clear where the guess came from.
            text = f"Focuses on {label}, like {match.via_circle}, a Circle you're in"
            reasons.append(Reason(code="related_to_your_circles", text=text))

    # 2. Activity. With no topic match, popularity is the main reason, so it leads and
    # replaces the plain active line instead of repeating it.
    if not match and very_active:
        about = f" on {topic_label(circle.topic, labels)}" if circle.topic else ""
        if cold_start:
            text = f"One of the most active Circles{about} right now, with {posts} in the last month"
        else:
            text = f"A popular Circle{about}, with {posts} in the last month"
        reasons.append(Reason(code="popular", text=text))
    elif circle.feed_posts_30d > 0:
        lead = "Very active" if very_active else "Active"
        reasons.append(Reason(code="active", text=f"{lead}, with {posts} in the last month"))

    # 3. Logistics. Only positives are listed. A Circle in another city simply gets no
    # location reason, and the client can still show its format.
    spots = circle.spots_left
    if spots is not None and 0 < spots <= config.FEW_SPOTS_LEFT:
        reasons.append(Reason(code="spots_left", text=f"Only {_plural(spots, 'spot')} left"))
    if scored.attend.kind == "near":
        # Says "leader" because the city comes from the leader's profile, not the Circle.
        text = f"Its leader is based in {scored.attend.city}, like you"
        reasons.append(Reason(code="near_you", text=text))
    elif scored.attend.kind == "virtual":
        reasons.append(Reason(code="virtual", text="Virtual, so you can join from anywhere"))
    if circle.join_policy == "open":
        reasons.append(Reason(code="open_to_join", text="Open to join"))
    else:
        reasons.append(Reason(code="request_to_join", text="Request to join"))

    return reasons


def build_explanation(reasons: list[Reason]) -> str:
    """Short explanation made of the topic and activity reasons plus the single best logistics fact."""
    chosen = [r for r in reasons if r.code not in LOGISTICS_PRIORITY]
    logistics = sorted(
        (r for r in reasons if r.code in LOGISTICS_PRIORITY),
        key=lambda r: LOGISTICS_PRIORITY.index(r.code),
    )
    chosen += logistics[:1]
    return " ".join(f"{r.text}." for r in chosen[: config.MAX_REASONS_IN_EXPLANATION])


def hint_for(personalization: str) -> str | None:
    """Nudge toward adding interests when we had to guess. None when the list is personalized."""
    if personalization == "cold_start":
        return "Add a few interests to your profile and we'll pick Circles just for you."
    if personalization == "memberships":
        return "Add your interests to your profile for more personalized picks."
    return None
