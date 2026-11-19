-- V3.167.17: инициализировать spicy_confidence_level=1 для всех отношений пользователей в режиме 18+
-- Запустить на Railway: psql $DATABASE_URL -f init_spicy_levels.sql

-- Обновить все отношения пользователей в режиме 18+, у которых spicy_confidence_level is NULL или 0
UPDATE user_character_relationships
SET spicy_confidence_level = 1,
    spicy_confidence_progress = COALESCE(spicy_confidence_progress, 0)
WHERE user_id IN (
    SELECT id FROM users WHERE explicit_mode = TRUE
)
AND (spicy_confidence_level IS NULL OR spicy_confidence_level = 0);

-- Показать результат
SELECT COUNT(*) as updated_rows
FROM user_character_relationships
WHERE user_id IN (
    SELECT id FROM users WHERE explicit_mode = TRUE
)
AND spicy_confidence_level = 1;
