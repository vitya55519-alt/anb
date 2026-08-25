# BUILD CHANGES V3.19.0 — WildGrl Feature Pack

Competitive feature pack based on the WildGrl (wildgrl.com) teardown: the six
biggest gaps between their product and the bot are now closed.

## 1. Video motion presets
- New `VIDEO_PRESETS` in `services/cloud_video_service.py`: kiss / hug / dance,
  each with an identity- and wardrobe-locked animation prompt.
- Every animation entry point (photo card, gallery, "animate last") now opens a
  preset picker first (`videopreset:<preset>:<delivery_id>`); "Авто" keeps the
  old scene-aware sensual prompt behavior.
- The selected preset travels through the Stars invoice payload
  (`video:<delivery_id>:<preset>`) into `_run_video_background` and all four
  video engines (Gemini/Veo, Replicate, fal.ai, HF) via the existing
  `prompt=` kwarg. Free/admin runs and refunds unchanged.

## 2. Vision reactions to user photos
- New `services/photo_reaction_service.py`: multimodal (OpenAI-compatible)
  call through the existing OpenRouter→Gemini chain; the active character
  reacts in-character to whatever the user sends (selfie, pet, food, gym...).
- Wired into the existing `F.photo` handler: ordinary users (and admins
  outside an import session) now get a reaction instead of silence.
- Cooldown (`PHOTO_REACTION_COOLDOWN_SECONDS`), fail-silent, no chat blocking.
- Sharing a photo records a `meaningful_share` relationship event (+bond).

## 3. Scenario hooks
- `SCENARIO_HOOKS` in `services/character_card_service.py`: a cinematic
  opening situation for anna_01, alena_01, maria_01, maksim_01, leo_01.
- Shown on the character card (`🎬 ...`) and sent as her first message right
  after the user selects the character.

## 4. Character trait bars
- `trait_bars()` in `services/character_dna_service.py` renders the 4 most
  distinctive DNA traits as `▓░` bars with x/10 scores on every character
  card. Hidden model-side numbers stay hidden from the LLM as before.

## 5. Personal character constructor
- New `services/custom_character_service.py`: 7 inline steps (age, body,
  hair, eyes, temperament, profession, relationship role) + free-text name +
  optional face photo. One-time Stars payment (`CONSTRUCTOR_COST_STARS`,
  default 50).
- New `CustomCharacter` model (`custom_characters` table; auto-migrated by
  the universal DB migration). Stable id `custom_<telegram_id>` plugs into
  chat history, memory and relationship rows.
- After payment the avatar is generated (`generate_custom_avatar` in
  photo_service: Seedream primary, Gemini fallback), a real `CharacterCard`
  is registered so photo pipelines recognize her, and chat switches to the
  persona via a system-prompt override (`custom_persona_context` injected in
  `chat_service.reply`).
- Entry points: "🎨 Мой персонаж" main-menu button and a
  "🎨 Создать свою · N⭐" row in the character picker. Failure refunds Stars
  automatically; `/cancel` aborts the wizard; `/delete_me` removes the row.

## 6. Face-swap character
- Optional wizard step uploads a face photo; it is passed to Seedream edit as
  the identity reference with an explicit "preserve the exact same face"
  lock, producing a character with the user's chosen face.

## Config
- `CONSTRUCTOR_COST_STARS` (default 50)
- `PHOTO_REACTION_ENABLED` (default true)
- `PHOTO_REACTION_COOLDOWN_SECONDS` (default 15)

## Tests
- `tests/test_v319_wildgrl_features_static.py`: 17 tests covering presets,
  payment payload wiring, vision guards, hooks, trait bars, constructor
  wizard/prompts/persona and face-swap anchoring.
- Full suite: see run results; no legacy assertions changed.
