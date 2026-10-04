# V3.51.0 — Playable stories in the Mini App, real branching, threshold scenes, live reaction

## Owner request
> «Продолжай» (V3.51 scope) + «если у тебя премиум то давай сделаем 4 задания в
> сутки, ну вот а где фото?» + «ну это задания, а сам квест где? который влияет
> на характер связи».

Locked design (owner decisions): the path-affecting quest becomes **playable in
the Mini App** (a new story player, not bot-only); the post-choice reaction is
**generated live by the LLM** with a curated fail-safe and written to the shared
dialog; **real branching** (a second "beat") on all 16 stories; **threshold
scenes** on the path axis (text at ±40, text + photo at ±70); the unlock ladder
is **tied to the story's own level** (`5 × min_level`); Premium gets **exactly 4
daily tasks**; photo requests typed into the app chat now deliver a real photo.
Everything in one V3.51 release.

## Unlock ladder to level (`services/quest_service.py`)
- `story_status`, `quest_task_threshold` and `newly_unlocked_quests` now compute
  `need_tasks = 5 * min_level` (was `5 * (index + 1)`). The double gate (level
  AND tasks) is unchanged; the level-5/6 dilemma quests now open at 25/30 tasks
  instead of 75/80. All three sources stay mutually consistent.

## Real branching — the second beat (`services/quest_service.py`)
- `QUEST_BRANCHES` maps every `(quest, route)` (32 pairs, all 16 stories) to a
  beat: a `prompt` + two options carrying inline `inclination` / `result` /
  `reaction` / `memory` (and an optional `photo_scene`). Beat inclinations stay
  OUT of `ROUTE_INCLINATION`, so the V3.50 axis pins are untouched.
- `complete_beat(...)`: only valid once the route is this story's **canonical**
  first choice; idempotent via a `route#option` token in `completed_routes_json`,
  so a beat can never be re-picked to farm the axis. Records a `story` Memory.

## Single resolver for both surfaces (`services/quest_service.py`)
- `resolve_story_choice` / `resolve_story_beat` (async) wrap `complete_route` /
  `complete_beat`, fire threshold scenes, produce the live reaction and return a
  surface-agnostic result. The bot (`quest_route_cb` + new `quest_beat_cb`) and
  the Mini App (`POST /webapp/api/story/action`) call the same functions — no
  duplicated branching/threshold/reaction logic.

## Threshold scenes (`services/relationship_engine.py` + `quest_service.py`)
- `PATH_EVENT_SOFT = 40`, `PATH_EVENT_DEEP = 70`; pure helper
  `path_crossings(old, new)` returns the tiers newly crossed (tender < 0,
  bold > 0).
- `_fire_path_events` records a one-shot `RelationshipMilestone` per direction ×
  depth (`path_event:{dir}:{soft|deep}`) — existence is checked first, so a
  scene never repeats. `deep` also attaches a `photo_scene` (delivered through
  the existing stage-allowed scene, no new gate). Four authored scenes in
  `PATH_EVENT_TEXTS`.

## Live reaction (`services/chat_service.py`)
- `story_reaction(...)` generates one short in-character line (`generate_text`,
  `purpose='dialogue'`, temp 0.95), fully fail-silent (returns `''` on any
  error). `_finalize_choice` falls back to the curated `reaction` and writes the
  winning line once into the shared `messages` (assistant), so both bot and app
  show it.

## Photo on request in the app chat (`main.py`)
- `_webapp_api_chat_send` now runs the bot's photo-intent routing
  (`_contextualize_vague_photo(parse_photo_request(text))`) **before** the text
  model. When the scene clears the same stage / 18+ / credit gates the app photo
  button enforces, a real photo is generated, saved to the shared dialog
  (`media_kind='photo'`) and returned with the caption — closing the «держи 📸»
  gap where the app only answered with text.

## Story player in the Mini App (`main.py` + `webapp/index.html`)
- `GET /webapp/api/story` serializes `story_status`; `POST /webapp/api/story/action`
  runs the shared resolvers and returns `result_text / reaction / path_axis /
  path_delta / path_events / beat_options / photo_url`.
- New `#storyview` overlay (modelled on `#featview`): list (🟢 available /
  🔒 level+tasks hint / ✅ done·canon) → intro + route buttons → result screen
  with reaction, path delta, second-beat options and photo. Rendered via `esc()`
  + concatenation (no raw interpolation).
- Entries: a chat pill «📖 Истории» and a character-card button right under the
  «💞 Характер связи» bar, tying choice → visible result. After an action the
  card's swing bar updates live (`renderPathBar` shared with V3.50). ru/en i18n.

## Premium daily tasks (`services/couple_service.py`)
- `daily_quests`: `count = 4 if is_premium(telegram_id) else (3 if seed % 2 == 0
  else 2)` with a lazy `is_premium` import (no import cycle). Rotation unchanged;
  the bot button and the app checklist pick up 4 items automatically.

## Tests
- Updated pins: `tests/test_v349_daily_task_gate_static.py` (ladder → `5 ×
  min_level`, premium = 4) — the V3.50 file stays green untouched.
- New: `test_v351_story_beats_static.py` (32-pair branch coverage via `ast`,
  complete_beat canonical/idempotent, beat callback + endpoint),
  `test_v351_path_events_static.py` (±40/±70, behavioral `path_crossings`,
  one-shot milestone, photo only on deep), `test_v351_live_reaction_static.py`
  (guarded LLM + curated fallback + single shared-dialog write),
  `test_v351_app_stories_static.py` (endpoints mounted, photo intent before the
  model, premium 4 tasks, player overlay + entries + photo render).

## Deploy notes
- No schema change: `path_axis` already exists, beats live in
  `completed_routes_json`, threshold scenes reuse the existing
  `RelationshipMilestone` table.
- `VERSION` not bumped (3.4x line).
- Alternative-branch replays remain a Stars flow in the bot; the app returns a
  `replay_locked` signal there.
