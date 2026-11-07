# Technical design: Recommend Circles to Join

## What I built

A FastAPI service on SQLite. `GET /users/{id}/recommendations` returns ranked Circles, each with a one-line explanation for the member, structured `reasons`, the leader's first name and job title, and near duplicates folded into `similar_circles`. `?debug=true` adds point breakdowns and the Circles that were ruled out. The schema and index rationale are in [SCHEMA.md](SCHEMA.md). The assumptions behind the rules are in the [appendix](#appendix-assumptions).

**Pipeline** (`app/recommender/`, all numbers in `app/config.py`):

1. **Retrieve** a shortlist through indexes: Circles on her topics, Circles with matching tags, and the most active public Circles with room. The full catalog is never loaded.
2. **Rule out** Circles she's already in, and any that are unlisted, full or inactive.
3. **Score** out of 100 points.
4. **Diversify** so near duplicates are shown once.
5. **Explain** in up to three sentences, each built only from a fact that earned points.

## Signals and why

| Signal | Points | Why |
|---|---|---|
| Stated interest = Circle's main topic | 45 | Her clearest statement of intent |
| Topic of a Circle she's already in | 22 | Real behavior, but weaker than stating it. Covers the 30 members with no stated interests |
| Tag overlap | 15 | Tags are noisy: 10 of 38 Circles don't list their own topic as a tag |
| Posts (capped), recency, chat, reactions per post | 30 | A dead Circle is a bad first experience. No single signal dominates |
| Open (10) or request to join (7) | 10 | Friction matters, but a request-only Circle can still be the best match |
| Format, plus a same-city bonus | 15 | Can she actually show up? |

**Not used:** photo and profile completeness (they describe her, not her fit with a Circle), job title, company and bio (free text), and description and cover image (not comparable without NLP).

**Example, user 7** (Seattle; leadership and public speaking): Women Who Lead scores 45+30+10+15 = **100**, and Speak Up Circle 45+26+10+8 = **89**. Elevation Circle scores 93 but shares a topic with Women Who Lead, so it is folded under it.

## Tradeoffs

- **Rules, not ML.** There are no labels (no impressions, joins or retention), and a model trained on 100 users and 40 Circles would memorize them, not learn. Rules keep every explanation true.
- **One Circle per topic** is a hard cap. It is simple, but a member with one interest gets one match and then popular fill. A softer diversity penalty (MMR) would allow a second strong match.
- **Borrowed interests recommend same-topic Circles.** That is useful for some members and redundant for others. It is an open product question.
- **Popularity concentrates.** 34 of 40 Circles appear across all users, and one of them appears for 55 users. That is fine for cold start, but at scale it starves new Circles.
- **Computed per request** (about 3 ms locally), so results are simple and always fresh.

## Production scale

- **Data:** Postgres with read replicas, and a `circle_stats` table fed by the event stream so requests never aggregate raw posts.
- **Serving:** retrieval is already index-backed. Cache each member's list briefly and invalidate it when she joins a Circle or edits her interests. Re-check capacity at join time, because a Circle can fill after it was shown.
- **Learning:** log impressions, joins, dismissals and 30-day retention. A/B test changes, then replace the hand-set weights with learning to rank.
- **Growth:** an exploration boost for new Circles, popularity ranked per region, and a real location on Circles.
- **Platform:** auth (`/me/recommendations`, with `debug` for staff only), rate limits, metrics, and explanations localized for 180+ countries.

## How I used AI

Claude Code was my pair programmer. I used it to read the brief, inspect the data and `generate.mjs`, plan, and scaffold code and tests. The planted scenario tests were written first, as the spec.

I came up with the scoring logic myself: which signals matter, how much each is worth, and what rules a Circle out. I explained it to the AI, then improved it by discussing it. For example, the tag weight was set after we checked how noisy tags are, and matching inferred interests against tags was dropped as noise.

I checked each data finding against the data, and overrode the AI where it went wrong:
- It penalized Circles whose leader is in a different city, which rests on an assumption. A different city now scores the same as an unknown one.
- It scored every Circle on every request. That is now index-backed retrieval, with a test proving the results match a full scan for all 100 users.
- Some explanations overclaimed, presenting tags as topics or saying "near you" based on the leader's city. I rewrote them.

## With more time

Co-membership ("members like you joined…"), topics inferred from job title and bio, embeddings to catch duplicates across topic slugs, "not interested" feedback, and small, welcoming Circles for new members.

---

## Appendix: Assumptions

The dataset leaves some things open. These are the calls I made and where each lives in the code.

**Data and time**
- The data is a frozen snapshot, so "now" is its latest timestamp (2026-09-21), not the wall clock. Otherwise every Circle would look stale. `REFERENCE_NOW` overrides it.
- The counters on `circles` (`member_count`, `feed_posts_30d`, `chat_messages_30d`, `last_activity_at`) are accurate and current. Engagement quality is computed from the posts in `activity.json`.
- `topic` is the source of truth for what a Circle is about. A tag match is explained as "Tagged X" rather than claiming the Circle covers it.

**Who can be recommended** (`app/recommender/eligibility.py`)
- Unlisted Circles are reachable by direct link only, so they are never recommended.
- A Circle is full when `member_count >= max_members`. A null `max_members` means uncapped.
- A Circle is inactive only when it has no feed posts in 30 days *and* no activity of any kind in 60. A Circle with no posts but recent chat is quiet, not dead.
- Needing approval to join is scored, not a rule-out.
- A member's existing Circles are excluded, whatever her role in them.

**Interests**
- Belonging to a Circle, as a member or a leader, means interest in its main topic. An inferred interest is used only for topics she hasn't stated.
- A member with neither interests nor Circles gets the most active healthy Circles on distinct topics, plus a hint to add interests.

**Location** (`attend_points` in `app/recommender/scoring.py`)
- Circles have no location field, so the leader's location stands in for where a Circle meets. This is the weakest assumption in the model, so it can only add points.
- Format is real data and carries most of the attend points. Virtual and hybrid Circles can be joined from anywhere.
- Cities match on exact text after trimming and lowercasing. "Remote" or a blank location counts as unknown.
- A different city scores the same as an unknown one. The leader may not live where the Circle meets, and text matching can't tell a nearby town from one across the country.
- The explanation says "Its leader is based in Seattle, WA, like you", not "near you", because the city belongs to the leader.

**Duplicates and display**
- Circles that share a main topic count as duplicates. The best one is listed, and the rest are returned in its `similar_circles`. Circles with no topic are never duplicates of each other.
- When a Circle has several leaders, the one who joined first is shown, with first name and job title only.
- Members never see scores. Point breakdowns appear only with `?debug=true`, which is meant for internal tools.
