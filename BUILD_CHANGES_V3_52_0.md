# V3.52.0 — «Жизнь без тебя» (proactive life moments) + Mini App unread badges

## Owner request
> «что ещё можно добавить, чтобы людей прям вовлечь, поднять хотя бы
> вовлечённость с 5%» … «у Лрики есть характер связи, у Евы нет, у Кристины нет,
> Мэри нет … общаюсь с одной и той же девушкой» … «допустим, у меня есть чаты,
> персонаж сама написала — чтобы отображалась как новое … удержание Д1 4%, Д7 1%,
> это из-за частых редиплоев».

Locked decisions (owner): pick idea **#2 «Она живёт без тебя»** — she writes first
about something from her own day (not a guilt / «почему не пишешь» nudge),
grounded in **the selected character's own personality** so the «все как Анна» gap
narrows; and any proactive message must show up as **unread in the Mini App
«Чаты» tab**. The dedup that was wiped by Railway redeploys (the D1/D7 leak) is
explicitly called out, so it must persist across restarts.

## 1. Life-moment engine (`services/life_event_service.py`, new)
- `build_life_moment(telegram_id, character_id, when)` composes ONE short (≤ ~200
  char) first-person slice of her day, always ending on an **open loop** (a mini
  question / intrigue) so replying is a single tap. Purpose `life_event`,
  `max_tokens=90`, `temperature=0.95`.
- Grounded per character: name + `stable_tastes` from `character_service`
  (constructor / community personas fall back to `custom_base_character`),
  temperament from `relationship_engine.PACE_HINTS.get(character_id, '')` — this
  is exactly the map that was EMPTY for kate/sasha/rex/custom_*, so they finally
  get a distinct voice instead of inheriting Anna's.
- Natural callbacks: ~45% the moment weaves in one `get_memories` fact, ~40% it
  resumes the user's own `pending_hook` (unfinished topic).
- Photo at `LIFE_EVENTS_PHOTO_CHANCE` only from `retention_features_service.
  random_proactive_photo()` — the existing owner media pool, **never a paid
  provider render**.
- Two universal tap-backs (`🍿 расскажи дальше`, `😏 скучал(а) по тебе`) whose
  callback value is `life_reply:{character_id}:{key}`.
- **Fail-silent**: any error / empty / text < 8 chars returns `{}` so a scan can
  never blank a conversation or spam a user.

## 2. Scheduler job (`services/scheduler_service.py`)
- `_life_events(bot)` scans every `LIFE_EVENTS_SCAN_MINUTES`, only targeting
  **recently-active opted-in** users (`proactive_enabled`, `notify_rituals !=
  False`, `last_active_at` within `LIFE_EVENTS_ACTIVE_WINDOW_DAYS`) — reward
  showing up, not chasing the already-churned (that stays `_proactive`).
- Per-user local-hour gating: skip the wrap-aware quiet window (`LIFE_EVENTS_
  QUIET_START_HOUR`→`LIFE_EVENTS_QUIET_END_HOUR`, default 23→7); the daypart
  (morning/day/evening/night) picks the framing.
- **Redeploy-safe dedup**: a `DialogStore('life_events')` (backed by
  `dialog_sessions`) keeps `{date, slots:[daypart,…]}` per telegram id, so a
  Railway restart cannot re-fire the same day's slot — the exact failure that
  made the old in-memory `_ritual_sent` guard double-send / under-send. Capped at
  `LIFE_EVENTS_MAX_PER_DAY` per day; a 0.35 per-scan probability sprinkles sends
  across the window instead of firing everyone at a boundary.
- The message is **persisted into the shared dialog** (`save_message(uid, char,
  'assistant', …)` + `webapp_service.save_chat_media` for the pool photo, at
  `/webapp/media/{filename}`) **before** delivery, so it lands in the Mini App
  history and the unread badge. Delivered via `send_message` / `send_photo` /
  `send_animation` / `send_video` with the inline tap-back keyboard. Tracked as
  `life_event_sent`. Registered in `start_scheduler` only when enabled.

## 3. Unread in the Mini App «Чаты» (`services/webapp_service.py` + `main.py` + SPA)
- Read-state lives in `DialogStore('chat_reads')` (again: survives redeploys, no
  new column). `mark_chat_read(telegram_id, character_id)` stamps the last-open
  ISO time per character.
- `api_chat_list` now returns `unread` per character = assistant messages newer
  than `max(last user turn, last opened)`; legacy assistant-only chats cap at a
  single «new» so a fresh «she wrote you» shows without flooding old history.
- `chat_service.reply` marks read the instant a conversational answer is produced
  (the user sees it live in bot + app), so only a LATER proactive message re-lights
  the badge. Opening a chat (`_webapp_api_chat_history`) also marks read.
- SPA `renderChats` draws a red pill from `c.unread`; `openChat` sets
  `_chatsLoaded = false` so the cleared badge is refetched on the next visit.

## 4. Tap-back continuation (`main.py`)
- `on_life_reply_tap` (callback prefix `life_reply:`) maps the key through
  `life_event_service.tap_reply_text` and feeds that natural user line into the
  SAME `anna_reply` pipeline the typed chat uses (memory / persona / relationship
  continuity), guarded by the daily message limit like a normal turn.

## Config (`config.py`)
Seven knobs, all env-overridable: `LIFE_EVENTS_ENABLED` (default on),
`LIFE_EVENTS_MAX_PER_DAY` (2), `LIFE_EVENTS_SCAN_MINUTES` (20),
`LIFE_EVENTS_ACTIVE_WINDOW_DAYS` (7), `LIFE_EVENTS_QUIET_START_HOUR` (23),
`LIFE_EVENTS_QUIET_END_HOUR` (7), `LIFE_EVENTS_PHOTO_CHANCE` (0.25).

## Tests
- New: `tests/test_v3520_life_events_static.py` (6 tests — config knobs; service
  grounding on PACE_HINTS/memories/pending_hook + free pool + `purpose='life_event'`
  + `life_reply:` + fail-silent `{}`; scheduler persists dedup via
  `DialogStore('life_events')` + `save_message`/`save_chat_media` + registered
  `id='life_events'`; `DialogStore('chat_reads')` + `mark_chat_read` + `unread`
  field + read-marking in reply/history; tap-back routed through `anna_reply`; SPA
  badge from `c.unread` + `_chatsLoaded = false` on open).
- Full suite: 17 failed / 946 passed / 1 error — exact baseline parity (940 → 946
  is the 6 new tests; the 17 + error are pre-existing and unrelated).

## Deploy notes
- No schema change: both new stores reuse the existing `dialog_sessions` table.
- `dialog_store.cleanup_stale_sessions(24h)` may drop an untouched life-events or
  read row after 24h idle — harmless: the day's slot resets anyway and unread
  recomputes from the last-user-turn anchor.
- Life events are near-zero marginal cost: no provider render, ≤ MAX_PER_DAY per
  user/day, only recently-active opted-in users, LLM only on the 0.35 sprinkle
  path.
- Backlog captured this cycle (owner, deferred): (a) upload-your-own-photo **in the
  Mini App** for a vision reaction — the bot already has this (V3.19.0
  `_react_to_user_photo` / `react_to_photo`), only the app upload UI is missing;
  (b) collection scale «N из M» under photos (`collection_service.collection_progress`
  already backs it); (c) dates as multi-photo sets priced 3 🍑 + 2 per extra.
- `VERSION` not bumped (3.5x line).
