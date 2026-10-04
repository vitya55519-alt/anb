# V3.49.0 — Daily tasks become the story-unlock currency

## Owner request
> «Сделать, чтобы открылся доступ к квесту — надо выполнить 5 миссий и так по
> нарастающей, а заданий будет 2–3 шт. в день.»

Locked design (owner decisions): the unlock currency is **completed daily
tasks** (renewable, 2–3/day), the ladder is **cumulative 5/10/15…** (5 × story
index), a story opens when **both** the relationship level **and** the task
counter pass, and each task pays **+5 attention** plus a **~20% spontaneous
free photo** (never peaches/Stars — V3.46.0 rule preserved).

## Data model (`models/app_models.py`, `User`)
- `quests_completed` (int) — lifetime count of claimed daily tasks (the ladder
  currency).
- `quest_claims` (str) — small JSON `{"YYYY-MM-DD": ["key", ...]}` of which of
  today's 2–3 tasks are done; the legacy single `quest_claimed_date` is kept in
  sync for old clients.
- `bonus_media_date` (str) — throttles the free-photo drop to ≤ 1/day.
All three are auto-migrated by `services/db.py::_auto_migrate_all_tables()` —
no manual migration and no `db.py` edit.

## Service (`services/couple_service.py`)
- `daily_quests(telegram_id)` — deterministic 2–3 quests/day (count and
  rotation both derive from the day+user md5 seed). `daily_quest(...)` stays as
  a thin wrapper returning the primary quest (V3.21 pins intact).
- `claim_quest(telegram_id, quest_key)` — idempotent per key per day; on a fresh
  claim: +5 attention, `quests_completed += 1`, and `_bonus_media_roll` (~20%,
  once/day). `claim_daily_quest(telegram_id)` remains as the legacy bool entry
  point (claims the primary quest).
- `daily_quests_state(telegram_id)` — today's quests with per-item `claimed`
  flags for the checklist.

## Story gate (`services/quest_service.py`)
- `story_status` now sets `unlocked = level_ok and tasks_ok`, where
  `tasks_ok = quests_completed >= 5 * (index + 1)`. It also returns
  `unlock_tasks`, `tasks_done`, `tasks_remaining` for the progress UI. This is
  the single source of truth read by both the bot keyboard and the app.
- `newly_unlocked_quests` no longer announces a quest whose task threshold has
  not been reached yet.

## API / bot / app
- `main.py` GET `feature?kind=quest` returns the `quests` checklist +
  `quests_completed` + `next_unlock` (title + remaining), keeping the legacy
  `text`/`claimed` fields.
- `main.py` POST `feature/action` accepts `quest_key`, claims by key, and on a
  lucky roll calls `_deliver_bonus_media` (picks a `ProactivePhoto`, saves it via
  `save_chat_media`, attaches an assistant photo message) and returns
  `photo_url` for a live bubble.
- Bot: `daily_quest_button` lists today's 2–3 tasks as per-key buttons
  (`questday:claim:<key>`); `daily_quest_claim` claims by key and mirrors the
  free photo with `_bot_deliver_bonus_media` (BufferedInputFile).
- `webapp/index.html`: `renderFeature` quest branch renders the checklist +
  progress hints; `featurePost` keeps the sheet open for `quest` and refreshes
  it; new `.qrow`/`.qprog` styles and `feat_tasks_left`/`feat_total` i18n.

## Tests
- `tests/test_v349_daily_task_gate_static.py` — 8 checks (columns, 2–3 quests +
  wrapper, keyed idempotency, capped roll, combined gate, no-peach delivery,
  app checklist, pure determinism).
- Updated pins: `test_v3210` (per-key callback) and `test_v3410`
  (`claim_quest(telegram_id, quest_key)`).

## Deploy notes
- Schema: 3 new nullable-default columns, auto-migrated on boot.
- `VERSION` not bumped (3.4x line).
- Existing `quest_claimed_date`-only users keep working; their `quests_completed`
  starts at 0, so early stories may need a few tasks — intended.
