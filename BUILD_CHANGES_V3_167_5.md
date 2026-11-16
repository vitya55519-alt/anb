# V3.167.5 — §9 аналитика рельсов, §10 миграции с журналом

ТЗ V3.167 «включить её жизнь» (автор Фогель, 16.11), последние два пункта. Рельсы
уже включены (V3.167.0–.2), первый ход живёт в Mini App (.3), события переписаны и
считаются по общему кадру, накопление и лестница замолкания — в нём же (.4). Это
замыкает блок: теперь по каждой рельсе видно, что она сделала, и число удержания
больше не тонет в аккаунтах, которые ничего не начали.

Цены, лимит 30 сообщений, персики, провайдеры, персонажи — не тронуты. Новых
бесплатных генераций не появилось: `push_sent`/`push_denied` — строки в уже
существующей таблице `product_events`.

## §9. Что теперь считается

События пишутся в `product_events` (`services/analytics_service.py`).

| Имя из ТЗ | Откуда берётся | Metadata |
|---|---|---|
| `push_sent(rail, …)` | выводится в `track_event` из любого физического имени рельса (`push_governor.FAMILY_EVENTS`) — ни один из 24 вызовов трогать не пришлось | `rail` (`life` / `ritual` / `scenario` / `marketing`), `kind` — прежнее имя, плюс метаданные исходного события |
| `push_denied(rail, reason)` | `push_governor._deny` —原先 жил только лог процесса | `rail`, `reason` (`night` / `burst` / `daily`) |
| `life_event_shown` | `scheduler_service._life_events`, после удачной отправки | `character_id`, `when`, `has_photo` |
| `life_event_replied` | `life_backlog.note_replied` на его ходу (вызывает `chat_service.reply` до записи его сообщения) | `character_id`, `unanswered`, `life` |
| `opening_shown` | `main._mark_opening_shown` — тем же условием, которым открывашка не приходит повторно | — |
| `streak_tick`, `streak_freeze` | `gamification_service.touch_activity` (один раз на сутки), `streak_freeze` ещё и в `series_reward._advance` | `streak`, `frozen` |
| `digest_shown` | `life_backlog.maybe_digest` (сводка на возврат; прежнее `life_digest_sent` прожило сутки и нигде не читалось — переименовано, вторую запись не заводим) | `character_id` |

Чего сознательно НЕ сделано: `push_sent` и `life_event_shown` не добавлены в
`push_governor.PUSH_EVENTS` — дневная норма считается по физическим именам, и
алиас внутри этого кортежа заставил бы каждый пуш тратить две сообщения нормы.
На это есть тест (`test_the_canonical_names_never_spend_the_day_budget`).

Отказ пишется не чаще раза на (аккаунт, рельс, причина) в сутки: сканер спрашивает
губернатора каждый час, и молчащий аккаунт залил бы журнал тысячами строк. Дедуп
держится в памяти процесса и в самом журнале (`_denial_memo` + один SELECT).

## §9. Чья строка в диалоге

У `messages` появилась колонка `origin` (`push` / `life` / `digest`, у обыкновенного
ответа — NULL). Без неё кап накопления V3.167.4 считал неотвеченными ВСЕ её строки
после его последнего сообщения, то есть и нормальный ответ ему, — и вставал на
сутки раньше, чем задумано. Теперь:

- `_to_app_chat(..., origin='push')` — весь scheduler разом, без правки 17 мест;
- `save_message(..., origin=LIFE_ORIGIN)` — её день в `_life_events` и в
  `live_situation_service.store_teaser`, `origin=DIGEST_ORIGIN` — сводка;
- `life_backlog.unanswered/missed/note_replied` фильтруют по `origin`.

Старые строки остаются NULL: они больше не считаются неотвеченными, кап после
релизда стартует с нуля. Это в сторону мягче, а не жёстче, и ровно то, что просил
ТЗ («после пропуска при возврате показывать до 3 накопленных»).

## §9. Когорта и экран кухни

- `ACTIVATION_MIN_MESSAGES` (default 12) — порог «дошёл», из ТЗ.
- `analytics_service.retention_cohorts((1,3,7))` — за один проход по когорте
  считает возврат и в бленде, и по когорте «дошёл до 12+».
- `analytics_service.rail_activity(days)` — кто заговорил, кого придержали и
  почему, `life_shown` / `life_replied`, доля ответов на её день и доля аккаунтов,
  получивших её событие в первые сутки (DoD «≥12%» и «≥70%»).
- `admin_snapshot()` отдаёт `d1_retention_activated`, `d7_retention_activated` и
  `rails`; кухня показывает их в обоих языках (`/📊 Статистика пользователей` и
  `/stats`).

Расход на пуши в долларах на аккаунт (DoD «не дороже $0.10/сутки») здесь не
появился: у владельца уже есть `spend_service` с ценой LLM и кадра на сутки, и
привязать его к одному аккаунту — отдельное решение, а не цифра из этого блока.

## §10. Миграции

`services/db.py`:

- журнал `app_migrations(name PRIMARY KEY, applied_at)` — идемпотентность теперь
  у всех миграций общая (`_ensure_migration_ledger`, `_already_applied`,
  `_mark_applied`); `_rescale_peaches` создал таблицу сам, теперь берёт общий
  помощник;
- `_add_missing_columns` и `_auto_migrate_all_tables`: одна транзакция на таблицу,
  каждая колонка с меткой `schema:<таблица>:<колонка>`, в лог — что добавлено и
  сколько строк было в таблице (`rows=`). Таблицы, где добавлена ровно половина
  колонок, быть не может: упало — откатилось, следующий старт повторяет целиком;
- `_index_analytics_stream()` — `ix_product_events_name_created (event_name,
  created_at)`, `IF NOT EXISTS`. На Postgres — `CREATE INDEX CONCURRENTLY` вне
  транзакции (обычный CREATE INDEX держал бы всю `product_events` записанной на
  время стройки, и бот встал бы посреди дня) плюс `SET lock_timeout '3s'`: не
  удалось — следующий старт догонит.

Идемпотентность проверена тестом: второй вызов не добавляет ни колонки, ни записи.

## Обратная миграция (лежит здесь текстом, не скриптом)

Исполняемый `DROP COLUMN` в репозитории — одноразовая граната, а откат релиза
владелец всегда делал флагом без редеплоя. Порядок отката, если понадобится:

```sql
-- 1. индекс (§10)
DROP INDEX IF EXISTS ix_product_events_name_created;
-- 2. колонка чьей-строки (§9): кап накопления вернётся к поведению V3.167.4
ALTER TABLE messages DROP COLUMN origin;      -- SQLite ≥3.35 / Postgres
-- 3. лента событий (§9): строки остаются, они больше никто не читает
DELETE FROM product_events WHERE event_name IN
  ('push_sent','push_denied','life_event_shown','life_event_replied',
   'digest_shown','opening_shown','streak_tick','streak_freeze');
-- 4. журнал: снять метки, иначе повторная миграция пропустит колонку
DELETE FROM app_migrations WHERE name LIKE 'schema:%';
```

Флаги, которыми релиз сворачивается без отката схемы: `PUSH_RAILS=` (пустой — все
рельсы стоят), `ACTIVATION_MIN_MESSAGES` (порог когорты), `SERIES_REWARD_ENABLED=0`
(награда за серию).
