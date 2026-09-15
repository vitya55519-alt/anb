# AnnaBot V3.41.0 — Per-Character Voice, Leaner Onboarding & App-Chat Feature Buttons

## «Все как Анна» is gone: every heroine speaks in her own voice
- `build_system_prompt` (`services/character_service.py`) now reads the per-character **`personality.communication`** profile (tone / length / humor / flirting / initiative) and builds a «СТИЛЬ ОБЩЕНИЯ (твой личный…)» block plus a character-specific «ФЛИРТ И ЧУВСТВЕННОСТЬ (твой персонажный стиль)» block from it.
- The old one-size-fits-all flirty template is now only a **fallback** for profiles that carry no `communication` block (e.g. constructor personas), so writing to a new heroine no longer answers in Anna's voice.

## Onboarding: the app is reachable from the very first screen
- The welcome/consent keyboard (`consent_keyboard`) keeps the 18+ gate + **📄 Условия / 🔐 Privacy** and adds a **📱 Открыть приложение** `web_app` tile right under the 18+ button (only when `PUBLIC_BASE_URL` is set).

## Onboarding: two walls removed
- After confirming 18+, the «Отлично, теперь выбери персонажа» message + inline character enumeration are gone — `consent_accept` now shows the persistent **main reply keyboard** (character selection lives in the Mini App). The «💖 Поддержать проект» donation appeal is kept.
- After picking a heroine, the «✨ Что умеет бот» text wall is no longer auto-sent — just the character card + a one-line «Основное меню всегда внизу 👇». `abilities_text` survives only as an on-demand helper (`/features`, `onboard:abilities`).

## Main menu: legal row pinned
- `MAIN_KB_ROWS` (`services/ui_lang.py`) keeps the app funnel and pins the **📜 Документы** (Условия + Privacy) row at the bottom: `app / credits / paint / partner+support / legal`. Character selection is gone from the chat funnel.

## App chat: the four missing feature buttons
- The in-app chat media strip gains **🎬 Видео**, **🎯 Задание дня**, **💕 Свидание** and **🏠 Квартира** (alongside the existing 📸 / 🎥 / 🎙), so the features the owner missed are now right in the dialog.
- **🎬 Видео** reuses the existing `requestMedia` → `POST /webapp/api/chat/media` pipeline: a new `video` kind + `_webapp_media_video` chains the same engines as the bot's «Оживить фото» (Gemini/Veo → Replicate → fal → HF), Premium-gated with its own free-slot check (a separate gate keeps the circle branch untouched). Rendered as a normal (non-round) `<video class="m">` clip.
- **🏠 / 💕 / 🎯** share one feature sheet (`#featview`) driven by two new endpoints: `GET /webapp/api/feature` renders the menu (apartment rooms / dates / daily quest, localized + level-gated) and `POST /webapp/api/feature/action` performs it.
  - **🏠 Квартира** reuses `apartment_service.room_action_reply` → relationship/intimacy deltas via `record_user_message`, the reply lands in the shared dialog.
  - **🎯 Задание дня** reuses the character-agnostic `couple_service.daily_quest` / `claim_daily_quest` (+5 attention, once/day, 409 on a repeat).
  - **💕 Свидание**: a free weekly-streak (or admin) date is delivered app-native (`_webapp_media_scene` identity-locked photo + narration into the shared history); a paid date returns a **Stars invoice** reusing the existing `date:` payload / `pre_checkout` / `successful_payment` path. `_deliver_date_reward` now mirrors the narration into the app/bot history so a date paid from the Mini App shows up in the app chat too.
- All new frontend HTML is built with string concatenation + `esc()` (no raw template interpolation), so the v3.34.0 «no unescaped backend strings in templates» guard stays green.

## Ops
- New endpoints: `GET /webapp/api/feature`, `POST /webapp/api/feature/action`; the chat-media endpoint accepts `kind='video'`.
- Tests: `tests/test_v3410_app_chat_features_static.py` (per-character prompt, consent app button, removed walls, legal row, video kind + engine chain, feature endpoints/routes, frontend buttons + wiring); all 30 version pins bumped to 3.41.0.
