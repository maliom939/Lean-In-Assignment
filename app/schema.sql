-- See docs/SCHEMA.md for the reasoning behind tables and indexes.

CREATE TABLE topics (
    id      INTEGER PRIMARY KEY,
    slug    TEXT NOT NULL UNIQUE,
    label   TEXT NOT NULL,
    domain  TEXT NOT NULL
);

CREATE TABLE users (
    id                    INTEGER PRIMARY KEY,
    first_name            TEXT    NOT NULL,
    last_name             TEXT    NOT NULL,
    has_photo             INTEGER NOT NULL CHECK (has_photo IN (0, 1)),
    bio                   TEXT,
    job_title             TEXT,
    company               TEXT,
    industry              TEXT,
    location              TEXT,
    joined_at             TEXT    NOT NULL,
    profile_completeness  REAL    NOT NULL CHECK (profile_completeness BETWEEN 0 AND 1)
);

CREATE TABLE user_topic_interests (
    user_id     INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    topic_slug  TEXT    NOT NULL REFERENCES topics (slug),
    PRIMARY KEY (user_id, topic_slug)
) WITHOUT ROWID;
CREATE INDEX idx_user_topic_interests_topic ON user_topic_interests (topic_slug);

CREATE TABLE circles (
    id                 INTEGER PRIMARY KEY,
    name               TEXT    NOT NULL,
    slug               TEXT    NOT NULL UNIQUE,
    description        TEXT,
    topic_slug         TEXT    REFERENCES topics (slug),
    cover_image_url    TEXT,
    format             TEXT    NOT NULL CHECK (format IN ('in_person', 'virtual', 'hybrid')),
    access             TEXT    NOT NULL CHECK (access IN ('public', 'unlisted')),
    join_policy        TEXT    NOT NULL CHECK (join_policy IN ('open', 'request')),
    max_members        INTEGER CHECK (max_members IS NULL OR max_members > 0),  -- NULL means uncapped
    member_count       INTEGER NOT NULL CHECK (member_count >= 0),
    created_at         TEXT    NOT NULL,
    last_activity_at   TEXT    NOT NULL,
    feed_posts_30d     INTEGER NOT NULL DEFAULT 0 CHECK (feed_posts_30d >= 0),
    chat_messages_30d  INTEGER NOT NULL DEFAULT 0 CHECK (chat_messages_30d >= 0)
);
CREATE INDEX idx_circles_topic ON circles (topic_slug);
-- Popularity pool used for cold start and list fill. Partial, so only discoverable Circles are indexed.
CREATE INDEX idx_circles_popular ON circles (feed_posts_30d DESC, last_activity_at DESC) WHERE access = 'public';

-- Tags are free text in the product, so there is no foreign key to topics.
CREATE TABLE circle_tags (
    circle_id  INTEGER NOT NULL REFERENCES circles (id) ON DELETE CASCADE,
    tag        TEXT    NOT NULL,
    PRIMARY KEY (circle_id, tag)
) WITHOUT ROWID;
CREATE INDEX idx_circle_tags_tag ON circle_tags (tag);

CREATE TABLE memberships (
    user_id    INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    circle_id  INTEGER NOT NULL REFERENCES circles (id) ON DELETE CASCADE,
    role       TEXT    NOT NULL CHECK (role IN ('member', 'leader')),
    joined_at  TEXT    NOT NULL,
    PRIMARY KEY (user_id, circle_id)
) WITHOUT ROWID;
CREATE INDEX idx_memberships_circle_role ON memberships (circle_id, role);

CREATE TABLE activity_posts (
    id              INTEGER PRIMARY KEY,
    circle_id       INTEGER NOT NULL REFERENCES circles (id) ON DELETE CASCADE,
    author_user_id  INTEGER NOT NULL REFERENCES users (id),
    body            TEXT    NOT NULL,
    reaction_count  INTEGER NOT NULL DEFAULT 0 CHECK (reaction_count >= 0),
    comment_count   INTEGER NOT NULL DEFAULT 0 CHECK (comment_count >= 0),
    save_count      INTEGER NOT NULL DEFAULT 0 CHECK (save_count >= 0),
    created_at      TEXT    NOT NULL
);
CREATE INDEX idx_activity_posts_circle_created ON activity_posts (circle_id, created_at);

CREATE TABLE dataset_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
) WITHOUT ROWID;
