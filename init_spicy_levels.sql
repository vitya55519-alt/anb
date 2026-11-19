-- V3.167.18. Запуск: psql $DATABASE_URL -f init_spicy_levels.sql
-- 18+ = users.spicy_mode. Premium = активная строка в subscriptions (колонки users.is_premium нет).

-- Premium 18+ -> уровень 10
UPDATE user_character_relationships
SET spicy_confidence_level = 10
WHERE user_id IN (
    SELECT u.id FROM users u
    WHERE u.spicy_mode = TRUE
      AND EXISTS (SELECT 1 FROM subscriptions s
                  WHERE s.user_id = u.id AND s.status = 'active' AND s.expires_at > NOW())
);

-- Остальные 18+ без уровня -> 1
UPDATE user_character_relationships
SET spicy_confidence_level = 1
WHERE (spicy_confidence_level IS NULL OR spicy_confidence_level = 0)
  AND user_id IN (SELECT id FROM users WHERE spicy_mode = TRUE);
