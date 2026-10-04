# V3.51.1 — Per-girl story progress + path bar, right-face bonus photo, admin generation feed

## Owner request
> «ну фото вообще другое, а где шкала романтики и разврата?» + «и сделай чтобы я
> видел что генерируется пользователями в миниап».

Locked decisions (owner): story progress becomes **per character** (each girl
keeps her own path and ladder); the daily-task bonus photo **generates the actual
character** being chatted; the generation viewer lives **inside the Mini App**
(hidden admin-only section) and is backed by a **new DB table** (survives
redeploys, images stay ephemeral).

## Per-character story progress (`services/quest_service.py`)
- Root cause of the missing scale: `UserQuestProgress` was keyed by the hardcoded
  `CHARACTER_ID` (Anna), so story completion was GLOBAL — a story done once read
  «Пройдено» for every girl and could never move another girl's axis.
- `progress`, `complete_route`, `complete_beat`, `story_status` and
  `newly_unlocked_quests` now take an optional `character_id` and key every
  `UserQuestProgress` (and `Memory`) row by `char_id = character_id or
  CHARACTER_ID`. Each girl tracks her own ladder and axis independently.
- Callers in `main.py` thread the current character through: `stories_keyboard`,
  `quest_routes_keyboard`, `_notify_quest_unlocks`, the app story `GET`/`POST`
  handlers — all resolve `character_id = get_user_character(telegram_id)` first.

## Path bar now appears (`services/quest_service.py`)
- `_apply_path` created the axis nudge only when a `UserCharacterRelationship`
  row already existed, so an untouched girl (e.g. Diana) had no row → the «Характер
  связи» swing bar stayed hidden. It now **creates a neutral row** (`path_axis=0.0`)
  and flushes before applying the step, so the axis persists and the bar renders.

## Right-face bonus photo (`main.py`)
- `_deliver_bonus_media` / `_bot_deliver_bonus_media` used
  `random_proactive_photo()`, which picks from the whole unfiltered
  `ProactivePhoto` pool (Anna's faces) — the delivered photo was «вообще другое».
- Both now `await _webapp_media_photo(telegram_id, character_id, 'selfie')`, so the
  daily-task bonus renders the character actually being chatted. `_deliver_bonus_media`
  became async; its caller awaits it.

## Admin generation feed (new)
- `models/app_models.py`: `UserGeneration` table (telegram_id, kind, character_id,
  prompt, filename, created_at) — indices on user/kind/time. Registered in
  `services/db.py` so `create_all` makes it.
- `services/webapp_service.py`: `record_generation(...)` (fire-and-forget, truncates
  kind/prompt/filename), `list_generations(limit, offset)` (newest-first), and
  `_is_admin(telegram_id)` (against `ADMIN_TELEGRAM_IDS`); `api_me` now exposes an
  `admin` flag.
- `main.py`: `record_generation` on the three app generation sites (picture studio,
  chat photo, chat media — non-voice). Two admin-gated endpoints:
  `GET /webapp/api/admin/generations` (list + `character` name + `thumb`) and
  `GET /webapp/api/admin/gen_media/{owner}/{filename}` (serves chat media or a
  picture file). Both reject non-admins.
- `webapp/index.html`: `#genview` overlay (modelled on `#storyview`), a
  profile-menu «🛠 Генерации пользователей» row shown only when `m.admin`, and
  `openGenFeed`/`loadGenFeed`/`renderGenFeed` with pagination. All rendering via
  `esc()` + concatenation. ru/en i18n.

## Tests
- Updated pin: `tests/test_v349_daily_task_gate_static.py` (bonus media now
  `_webapp_media_photo(` instead of `random_proactive_photo()`).
- New: `tests/test_v3511_perchar_generations_static.py` (8 tests — per-character
  progress signatures + `character_id == char_id` keying, `_apply_path` row
  creation, callers pass the character, right-face bonus photo + no
  `random_proactive_photo` in the bonus feature, bot mirror, `UserGeneration`
  model + DB registration, the 3 `record_generation` call sites, admin endpoints +
  routes + `_is_admin` gating + `api_me` admin flag, and the `#genview`/`openGenFeed`/
  `renderGenFeed`/`menuGen`/i18n webapp surface).
- Full suite: 17 failed / 933 passed / 1 error — exact baseline parity (the 17 +
  error pre-date this work and are unrelated).

## Deploy notes
- New table `user_generations` is created on startup by `Base.metadata.create_all`;
  no migration needed. Generated image files stay ephemeral on Railway (only the
  DB audit rows + git-committed files persist), so the feed shows prompts and, when
  the file still exists, a thumbnail.
- `VERSION` not bumped (3.5x line).
