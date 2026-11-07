# Circle Recommendations API

## Overview

Lean In Circles are small peer groups where women support each other's careers. With thousands
of Circles, a member needs help finding the few that fit her goals, are active, and still have
room. This API takes a member's id and returns a ranked list of Circles she should join, each
with a short explanation written for her ("Matches your interest in Negotiation. Very active,
with 13 posts in the last month. Open to join.").

It is the take-home for the Lean In Software Engineer role, built on the synthetic dataset
described [below](#seed-dataset--recommend-circles-to-join).

## Features

- **Personalized ranking** from stated interests, falling back to the topics of Circles the member is already in.
- **Cold start handling.** A member with no interests and no Circles gets the most active healthy Circles on different topics, plus a hint to add interests.
- **Hard filters.** Circles that are full, inactive or unlisted, or that she already belongs to, are never recommended.
- **Duplicate collapsing.** Near-identical Circles on one topic appear once, with the rest listed as `similar_circles`.
- **Explanations members can trust.** Every sentence comes from a fact that earned points, and scores are never shown to members.
- **Debug mode.** `?debug=true` shows the point breakdown per Circle and every Circle that was ruled out, with the reason.
- **Built to scale.** Index-backed candidate retrieval (the full catalog is never loaded), a read-only database connection, health and readiness checks, request IDs and access logs.
- **Tested.** 291 tests cover the seed data, queries, API, the four planted scenarios, invariants for all 100 users, and retrieval against a full scan.

## Prerequisites

- **Python 3.10 or newer.** SQLite ships with Python, so there is no database server to install.
- Dependencies, pinned in [`requirements.txt`](requirements.txt):

| Package | Version | Used for |
|---|---|---|
| fastapi | 0.162.0 | Web framework and OpenAPI docs |
| uvicorn[standard] | 0.54.0 | ASGI server |
| pydantic | 2.14.3 | Response models and validation |
| pytest | 9.2.0 | Test runner |
| httpx | 0.28.1 | HTTP client for API tests |

## Installation

```bash
git clone [<repo-url>](https://github.com/maliom939/Lean-In-Assignment.git)
cd circle-recommendations-takehome-main

python -m venv .venv
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python -m app.seed          # loads data/*.json into ./recs.db
```

Run `python -m app.seed` again at any time to rebuild the database. It is rebuilt in a temporary
file and swapped in, so a failed load never leaves a broken database.

## Running

```bash
uvicorn app.main:app --reload       # API at http://localhost:8000, Swagger UI at /docs
pytest -q                           # full test suite, uses its own temporary database
python scripts/show_scenarios.py    # prints the four planted scenarios with scores
```

| Endpoint | Description |
|---|---|
| `GET /users/{user_id}/recommendations` | Ranked Circles with explanations. Query parameters: `limit` (1 to 20, default 5) and `debug` (default false). Returns 404 for an unknown user, 422 for invalid parameters, and 503 if the database isn't seeded. |
| `GET /health` | Liveness check. |
| `GET /ready` | Readiness check. Returns 503 until the database is seeded. |
| `GET /docs` | Interactive Swagger UI. |

## Configuration

All settings are optional environment variables. The ranking weights and thresholds are code, in
[`app/config.py`](app/config.py), so changes to them go through review and the tests.

| Variable | Default | Description |
|---|---|---|
| `RECS_DB_PATH` | `./recs.db` | Path to the SQLite database, used by both the seed loader and the API |
| `REFERENCE_NOW` | latest timestamp in the data (`2026-09-21T00:00:00Z`) | The "now" that activity and recency are measured from. Must be ISO 8601. An invalid value stops the service at startup |
| `LOG_LEVEL` | `INFO` | `DEBUG` also logs candidate and scoring counts per request |

Every response carries an `X-Request-ID` header, which is the caller's id if it sent a valid one.
The same id appears in the access log.

## Usage examples

**A member with clear interests** (user 7, interested in leadership and public speaking):

```bash
curl "http://localhost:8000/users/7/recommendations?limit=2"
```

```json
{
  "user_id": 7,
  "reference_time": "2026-09-21T00:00:00Z",
  "personalization": "interests",
  "recommendations": [
    {
      "rank": 1,
      "circle": {
        "id": 5, "name": "Women Who Lead", "topic": "leadership-skills",
        "topic_label": "Leadership skills", "format": "hybrid", "join_policy": "open",
        "member_count": 24, "max_members": 31, "spots_left": 7
      },
      "explanation": "Matches your interest in Leadership skills. Very active, with 11 posts in the last month. Its leader is based in Seattle, WA, like you.",
      "reasons": [
        { "code": "topic_match", "text": "Matches your interest in Leadership skills" },
        { "code": "active", "text": "Very active, with 11 posts in the last month" },
        { "code": "near_you", "text": "Its leader is based in Seattle, WA, like you" },
        { "code": "open_to_join", "text": "Open to join" }
      ],
      "leader": { "first_name": "Ingrid", "job_title": "Recruiter" },
      "similar_circles": [
        { "id": 1, "name": "The Elevation Circle" },
        { "id": 35, "name": "Board-Ready Women" }
      ]
    },
    {
      "rank": 2,
      "circle": { "id": 6, "name": "Speak Up Circle", "topic": "public-speaking", "...": "..." },
      "explanation": "Matches your interest in Public speaking. Very active, with 8 posts in the last month. Open to join.",
      "...": "..."
    }
  ]
}
```

**Why a Circle was left out** (user 23, debug mode, trimmed):

```bash
curl "http://localhost:8000/users/23/recommendations?limit=1&debug=true"
```

```json
{
  "recommendations": [
    {
      "rank": 1,
      "circle": { "id": 22, "name": "Level Up Collective", "join_policy": "request", "...": "..." },
      "explanation": "Matches your interest in Getting promoted. Very active, with 8 posts in the last month. Request to join.",
      "score": { "topic": 45, "activity": 28, "join": 7, "attend": 12, "total": 92 }
    }
  ],
  "debug": {
    "excluded": [
      { "id": 20, "name": "The Promotion Path", "reason": "full" },
      { "id": 21, "name": "Career Climbers", "reason": "unlisted" },
      { "id": 23, "name": "Allies at Work", "reason": "already_member" },
      { "id": 32, "name": "The Resilience Room", "reason": "inactive" }
    ]
  }
}
```

**Other cases worth trying:** user 42 (cold start, returns a `hint`) and user 15 (three near-identical
Negotiation Circles collapse into one).

## Documentation

- [Technical design](docs/DESIGN.md): what was built, the signals and why, tradeoffs, production scale, AI usage, and the assumptions behind the rules.
- [Database schema](docs/SCHEMA.md): tables, relationships, and the query each index serves.
- [Seed dataset](#seed-dataset--recommend-circles-to-join): the files and data dictionary, below.
- Interactive API docs at `http://localhost:8000/docs` once the server is running.

### Project layout

```
app/
  main.py          FastAPI routes, error handling, request logging
  config.py        settings and the scoring rubric (all ranking numbers live here)
  schema.sql       SQLite schema
  seed.py          JSON to SQLite loader
  repository.py    all SQL (candidate retrieval, scoped lookups), returns dataclasses
  models.py        API response models
  timeutil.py      timestamp parsing and formatting
  recommender/     retrieval, rule-outs, scoring, diversification, explanations
tests/             pytest suite (temporary database per run)
scripts/           demo script
docs/              design doc and schema
data/              seed dataset (unchanged)
```

---

# Seed dataset — Recommend Circles to Join

This folder is the dataset for the take-home. It's a small, **fully synthetic** snapshot
of a Lean In Connect–style community: members, Circles, who belongs to which Circle,
the topic taxonomy, and recent Circle feed activity.

Everything here is generated (`generate.mjs`) — no real people, no real content.

## Files

| File | Rows | What it is |
| --- | --- | --- |
| `data/topics.json` | 22 | The topic taxonomy Circles and members are tagged with |
| `data/users.json` | 100 | Members: profile fields + stated topic interests |
| `data/circles.json` | 40 | Circles: profile, topic, capacity, and activity aggregates |
| `data/memberships.json` | ~440 | Who belongs to which Circle, and their role |
| `data/activity.json` | ~390 | Recent Circle feed posts with engagement counts |

## Loading it

The data is plain JSON so it drops into anything — Postgres, SQLite, or just an
in-memory array. Load it however suits your design; you don't have to mirror our shapes.

```js
const users = JSON.parse(fs.readFileSync("data/users.json", "utf8"));
```

## Data dictionary

### `topics.json`
| field | type | notes |
| --- | --- | --- |
| `id` | int | |
| `slug` | string | kebab-case, e.g. `negotiation` |
| `label` | string | display name |
| `domain` | string | always `content` here |

### `users.json`
| field | type | notes |
| --- | --- | --- |
| `id` | int | |
| `first_name`, `last_name` | string | synthetic |
| `has_photo` | bool | whether a profile photo is set |
| `bio` | string \| null | |
| `job_title` | string \| null | |
| `company` | string \| null | |
| `industry` | string \| null | |
| `location` | string \| null | |
| `joined_at` | ISO datetime | account age / tenure signal |
| `topic_interests` | string[] | topic slugs the member selected; **may be empty** |
| `profile_completeness` | number 0–1 | share of {photo, bio, job title, company-or-industry, location} present |

### `circles.json`
| field | type | notes |
| --- | --- | --- |
| `id` | int | |
| `name`, `slug`, `description` | string / null | `description` and `cover_image_url` may be null |
| `topic` | string \| null | topic slug; **some Circles have no topic** |
| `tags` | string[] | free-form topic-ish tags |
| `cover_image_url` | string \| null | |
| `format` | enum | `in_person` \| `virtual` \| `hybrid` |
| `access` | enum | `public` \| `unlisted` |
| `join_policy` | enum | `open` \| `request` |
| `max_members` | int \| null | capacity; **null means uncapped** |
| `member_count` | int | current members |
| `created_at` | ISO datetime | |
| `last_activity_at` | ISO datetime | timestamp of the most recent activity |
| `feed_posts_30d` | int | posts in the last 30 days |
| `chat_messages_30d` | int | group-chat message volume in the last 30 days (aggregate count only) |

### `memberships.json`
| field | type | notes |
| --- | --- | --- |
| `user_id` | int | → `users.id` |
| `circle_id` | int | → `circles.id` |
| `role` | enum | `member` \| `leader` (a Circle's leaders are just members with `role=leader`) |
| `joined_at` | ISO datetime | |

### `activity.json`
| field | type | notes |
| --- | --- | --- |
| `id` | int | |
| `circle_id` | int | → `circles.id` |
| `author_user_id` | int | → `users.id` (always a member of that Circle) |
| `body` | string | post text |
| `reaction_count`, `comment_count`, `save_count` | int | engagement on the post |
| `created_at` | ISO datetime | |

## A few things are intentionally *derived*, not stored

Mirroring the real product, some signals aren't handed to you as a column — you decide
how to compute them:

- **Is a Circle full?** Compare `member_count` to `max_members` (and `max_members` can be null).
- **How active is a Circle?** Combine `feed_posts_30d`, `last_activity_at`, `chat_messages_30d`,
  and engagement in `activity.json` however you think best.
- **A Circle's leaders and their profiles** come from `memberships` (`role=leader`) joined to `users`.

## What we deliberately did *not* include

- **Embeddings / precomputed similarity.** Topic overlap and the fields above are enough for this exercise.
- **Raw group-chat message text.** Only the aggregate `chat_messages_30d` count, for privacy realism.

## Named records for the scenarios

The assignment says we'll run your submission against planted records. Here they are —
build so these return sensible results, and be ready to talk through them:

| Scenario | Run for | What's planted |
| --- | --- | --- |
| **Cold start** | `user_id 42` | No memberships, no stated interests, empty profile (`profile_completeness = 0`) |
| **Obvious matches** | `user_id 7` | Interests `leadership-skills`, `public-speaking`; strong active/open Circles exist for both (`#5 Women Who Lead`, `#6 Speak Up Circle`) that she hasn't joined |
| **Duplicate Circles** | `user_id 15` | Interest `negotiation`; Circles `#10`, `#11`, `#12` are three near-identical active Negotiation Circles — a good list shouldn't return all three |
| **Full / inactive** | `user_id 23` | Interest `getting-promoted`; `#20 The Promotion Path` is **full** (at capacity) and `#21 Career Climbers` is **inactive** (no posts in ~7 months) — both look like great topic matches but shouldn't rank; `#22 Level Up Collective` is the healthy alternative |

Regenerate the data anytime with `node generate.mjs` (it's deterministic — same output every run).
