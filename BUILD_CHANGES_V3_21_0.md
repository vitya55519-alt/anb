# BUILD CHANGES V3.21.0 — couple layer & simple visible interface

Owner request: implement the full relationship/UI improvement list (items
1–16) and make every feature visible in one simple menu ("as an admin I
could not even find circles").

## Relationship levels: 8 instead of 6

- Emotional level names replace numbers everywhere: 1 Знакомство →
  2 Симпатия → 3 Флирт → 4 Влюблённость → 5 Любовники → 6 Наша история →
  **7 Родственные души** → **8 Одно целое**.
- Levels 7–8 are a **premium-only plateau**: `relationship_engine` gained
  `set_premium_checker`, and `apply_delta` clamps free users at
  «Наша история». `main.py` registers a checker that translates the
  internal user id back to a Telegram id (`_premium_by_internal_uid`).
- New plateau content: room «Комната со свечами» (level 7) and dates
  «СПА для двоих» (7) / «Ночь вместе» (8). Room/date ceilings moved 6 → 8.
- `photo_service.STAGE_INDEX` extended with `devoted`/`soulmate`;
  `test_mode` covers all 8 stages; LLM context blocks describe the two
  new stages.

## New couple mechanics (`services/couple_service.py`)

- **Pet name**: at the level-3 ceremony she picks one of 8 Russian pet
  names once (`User.pet_name`); `relationship_service` injects it into the
  conversation context so she uses it naturally.
- **Daily quest**: one deterministic small request per day
  («сделай комплимент», «спроси, что снилось»…); claiming it grants
  +5 attention points, once per day (`User.quest_claimed_date`).
- **Couple album**: one milestone photo per level (`CoupleAlbum`); every
  successful photo delivery registers the current level idempotently.
  Progress shown in the profile («💑 Наш альбом: N/8»).
- **Anniversaries**: 7/30/90 days together are celebrated once each with
  an in-character push + achievements `anniv_7/30/90`
  (`User.anniversaries` stores celebrated days).

## Interface: everything on the first row

- `main_keyboard` redesigned: new buttons «🎬 Видео», «🎥 Кружочек»,
  «🎯 Задание дня» sit in the top rows next to photos/dates/apartment.
  Nothing is buried in sub-menus anymore; the circle flow is reachable
  in one tap.
- «🎬 Видео» and «🎥 Кружочек» route into the existing inline flows
  (`video:animate_last`, `video:circle`) — single source of truth.
- **One-time onboarding tour** (`User.tour_done`): after character
  selection a short walkthrough explains every button.
- **Profile** now shows hearts progress (`❤️❤️❤️🤍🤍` + `уровень X/8`),
  the premium plateau hint for level-6 free users, album progress and the
  pet name.
- **Settings** gained the rituals line + «🔔 Ритуалы» toggle
  (`toggle:rituals`, `User.notify_rituals`); the scheduler `_rituals` job
  skips opted-out users (`notify_rituals != False`, NULL = legacy on).
- Premium pitch lists the 7–8 plateau; the plateau line for maxed free
  users names both premium levels. Welcome/abilities texts say 1–8.

## Files

- `main.py`, `models/app_models.py` (5 new User columns + CoupleAlbum),
  `services/couple_service.py` (new), `services/relationship_engine.py`,
  `services/relationship_service.py`, `services/apartment_service.py`,
  `services/dates_service.py`, `services/gamification_service.py`,
  `services/photo_service.py`, `services/scheduler_service.py`,
  `services/test_mode.py`.
- `tests/test_v3210_couple_ui_static.py`: pins the level ladder, plateau
  gate, discovery buttons, daily quest, pet name ceremony, album hook,
  anniversaries, tour, rituals opt-out and pitch wording.
- Updated stale pins: `test_v3163` (levels 1–6 → 1–8), `test_v317`
  (room/date ceilings 6 → 8, new candles room).
