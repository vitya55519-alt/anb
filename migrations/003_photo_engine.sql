-- Photo Engine v2 tables for production PostgreSQL.
CREATE TABLE IF NOT EXISTS photo_daily_usage (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    character_id VARCHAR(64) NOT NULL,
    usage_date DATE NOT NULL,
    free_used INTEGER NOT NULL DEFAULT 0,
    paid_used INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_photo_daily_usage UNIQUE (user_id, character_id, usage_date)
);
CREATE INDEX IF NOT EXISTS ix_photo_daily_usage_user_id ON photo_daily_usage(user_id);
CREATE INDEX IF NOT EXISTS ix_photo_daily_usage_character_id ON photo_daily_usage(character_id);
CREATE INDEX IF NOT EXISTS ix_photo_daily_usage_usage_date ON photo_daily_usage(usage_date);

CREATE TABLE IF NOT EXISTS photo_deliveries (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    character_id VARCHAR(64) NOT NULL,
    scene VARCHAR(32) NOT NULL,
    delivery_type VARCHAR(16) NOT NULL,
    telegram_file_id VARCHAR(512),
    image_url TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_photo_deliveries_user_id ON photo_deliveries(user_id);
CREATE INDEX IF NOT EXISTS ix_photo_deliveries_character_id ON photo_deliveries(character_id);
CREATE INDEX IF NOT EXISTS ix_photo_deliveries_created_at ON photo_deliveries(created_at);

CREATE TABLE IF NOT EXISTS photo_offers (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    character_id VARCHAR(64) NOT NULL,
    scene VARCHAR(32) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    consumed BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_photo_offers_user_id ON photo_offers(user_id);
CREATE INDEX IF NOT EXISTS ix_photo_offers_character_id ON photo_offers(character_id);
