-- PostgreSQL schema for per-user/per-character relationship state.
-- Safe to run after the base application tables exist.

CREATE TABLE IF NOT EXISTS user_character_relationships (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    character_id VARCHAR(64) NOT NULL,
    relationship_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    trust_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    intimacy_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    stage VARCHAR(32) NOT NULL DEFAULT 'stranger',
    first_interaction_at TIMESTAMPTZ,
    last_interaction_at TIMESTAMPTZ,
    total_messages INTEGER NOT NULL DEFAULT 0,
    consecutive_days INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_user_character_relationship UNIQUE (user_id, character_id),
    CONSTRAINT ck_relationship_score CHECK (relationship_score BETWEEN 0 AND 100),
    CONSTRAINT ck_trust_score CHECK (trust_score BETWEEN 0 AND 100),
    CONSTRAINT ck_intimacy_score CHECK (intimacy_score BETWEEN 0 AND 100)
);

CREATE INDEX IF NOT EXISTS ix_ucr_user_id ON user_character_relationships(user_id);
CREATE INDEX IF NOT EXISTS ix_ucr_character_id ON user_character_relationships(character_id);

CREATE TABLE IF NOT EXISTS relationship_events (
    id BIGSERIAL PRIMARY KEY,
    user_character_id BIGINT NOT NULL REFERENCES user_character_relationships(id) ON DELETE CASCADE,
    event_type VARCHAR(64) NOT NULL,
    relationship_delta DOUBLE PRECISION NOT NULL DEFAULT 0,
    trust_delta DOUBLE PRECISION NOT NULL DEFAULT 0,
    intimacy_delta DOUBLE PRECISION NOT NULL DEFAULT 0,
    reason TEXT,
    metadata_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_relationship_events_pair ON relationship_events(user_character_id);
CREATE INDEX IF NOT EXISTS ix_relationship_events_created_at ON relationship_events(created_at);
