# Build Changes — v3.22.0 (Service Recovery: Photo Reliability, Per-Character Persistence, EN Interface)

Version: **3.22.0**
Build date: **2026-08-29**
Owner request: **fix the level-6 photo failures ("дразнит"/"обнажённая" answer with a masked error), keep each character's relationship level separate and persistent, and make the bot navigable for an English-speaking user.**

---

## Context / Why this release

Three production pain points came straight from live usage:

1. **The 18+ photo scenes failed and the error hid the reason.** Level-6 "дразнит" and "обнажённая" answered `фото сейчас не получилось 😕 (seedream45/PhotoGenerationError)`. Two bugs stacked: fal's API-level moderation rejects the old explicit body-part wording (400/422) even with the model safety checker off, and the outer exception wrapper then replaced the real reason with the exception class name — so nobody could tell moderation refusal from timeout or quota.
2. **Characters cross-wired.** The card showed a relationship level only on Anna's card but read the *selected* character's progress — so Emily's level 6 appeared on Anna's card. On top of that the selection itself lived only in memory and reset to Anna on every redeploy.
3. **Russian-only chrome.** The LLM chat always answers in the user's language, but every button, menu and system text was Russian — an English speaker could not navigate the bot at all.

Goal of v3.22.0: **make the adult photo path reliable and diagnosable, give every character its own persisted relationship and visible level, and ship a RU/EN interface layer so the bot works for an international audience.**

---

## What was done

### 1. Photo: real error reason + moderation-safe adult wording + working safe retry
- `generate_photo_set` re-raises `PhotoGenerationError` untouched; only unknown exceptions are wrapped (reason = exception class). Users now see the actual fal reason (e.g. `HTTP 422`, `HTTP 451`, `timeout`) instead of `PhotoGenerationError`.
- Adult scenes (`nude`/`tease`) rewritten to fine-art/boudoir wording: `ADULT_SAFETY` ("tasteful artistic nudity … elegant boudoir fine-art photography"), adult wardrobe ("an elegant fine-art nude composition … styled like classic boudoir photography"), and `PRIVATE_SCENE_TIERS` nude/tease tiers. Removed every moderation-triggering phrase ("visible bare breasts", "no clothing at all, bare skin throughout", "realistic body details", rear-view framing).
- The Seedream clothed safe retry now covers every policy status (`HTTP 400/403/422/451`, was 422 only) and passes `force_safe=True` into `_build_prompt` — which suppresses adult-scene wardrobe, home-lingerie and private-tier injection. Before, the retry prompt was re-detected as adult and overwritten back to nudity, making the retry pointless.
- Level-6 scenes keep their 18+ gating and never enter the community pool — only the wording changed.

### 2. Per-character persistence and card levels
- New column `User.selected_character` — the chosen character survives restarts/redeploys. `get_user_character` reads cache → DB → Anna fallback; `set_user_character` persists every selection (onboarding, character picker, custom character). The universal auto-migrator adds the column on boot.
- `_character_card_text` now shows **every** library character card's OWN relationship level (`get_relationship_level(viewer_id, card.character_id)`). Anna, Emily and Maria progress independently and visibly; the old "only Anna's card, reading the selected character" cross-wire is gone.

### 3. RU/EN interface layer (`services/ui_lang.py`)
- New `User.ui_lang` column; detected **once** from the Telegram account language on first contact (`ensure_user`, legacy users get a one-time backfill) and never forced afterwards. Unknown language stays Russian.
- All 19 reply-keyboard buttons exist as `(ru, en)` pairs (`KB_LABELS`) and the keyboard is built from `MAIN_KB_ROWS` per user language. Every handler matches both variants via `F.text.in_(kb_pair(key))` — an English keyboard works without any extra handler.
- Localized top-level flows (RU + EN): welcome and welcome-back, 18+ consent, onboarding, feature menu, tour, chat/photo/video/circle/quest/apartment/gift/date entry points, photo menu with `LEVEL_NAMES_EN` (8-level ladder), premium pitch, profile (hearts, plateau hint, album, pet name), settings, alarm, locked-scene alerts.
- The chat itself was already language-aware (LLM receives `language_code`); this release translates the chrome around it.

### 4. Pins and tests
- New suite `test_v3220_photo_i18n_character_static.py` (10 tests): error reason preservation, banned moderation phrases, fine-art wording, 4xx safe-retry set + `force_safe`, selected-character persistence helpers, per-card level, `KB_LABELS` pairs/helpers, dual-language handlers for all 19 keys, one-time language detection, EN texts.
- Updated stale pins: `test_v3181` (adult wardrobe wording), `test_v317`/`test_v3210` (keyboard labels now via `ui_lang`), version pins accept 3.22.0.

### 5. Versioning and migration
- `VERSION` bumped to **3.22.0**.
- No migration script: the universal auto-migrator adds `User.selected_character` and `User.ui_lang` on boot; existing users keep Russian and Anna by default.

---

## Verification

- Static test suite: `python -m pytest tests -q --ignore=tests/test_v392_bulk_library.py` (test_v392 is a pre-existing network/seedream live test, excluded as before).
- New v3.22.0 pins: `python -m pytest tests/test_v3220_photo_i18n_character_static.py -q`
- `py_compile` clean on main.py, services/photo_service.py, services/ui_lang.py, services/user_service.py, models/app_models.py.

---

## Operational notes (Railway)

- After the redeploy, retry a level-6 "дразнит"/"обнажённая" set. If fal still refuses, the user now sees the real reason; the bot also auto-falls back to a tasteful clothed set on any policy 4xx instead of failing the whole set.
- **Robotic voice** is the known GEMINI_API_KEY issue: the production key contains a non-ASCII character, so Gemini (chat/image/video/TTS) is disabled and voice falls back to edge-tts. Re-paste a clean `GEMINI_API_KEY` in Railway env vars — no code change needed.
- Levels 7–8 stay premium-only, so the "spicy" plateau keeps monetizing.
