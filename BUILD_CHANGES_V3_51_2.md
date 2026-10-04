# V3.51.2 — First-person POV date photos + uncensored studio leg

## Owner request
> «сделать промпт под свидание, сам пользователь, типа вот его рука, и он с ней
> идет … типа реально свидание было» + «я хотел сгенерировать, а он не выдал, а
> ошибочку» (студия «Картинки» отдала HTTP 422 на явный промпт).

Locked decisions (owner): the date reward photo becomes a **first-person POV** —
his hand holding hers in the foreground, her seen ahead at arm's length, so it
reads like a real photo the user took on the date; the studio gets an **NSFW /
uncensored leg** so an explicit prompt actually renders instead of dying on the
provider's content filter.

## POV date photos (`services/dates_service.py` + `main.py`)
- `DATE_POV_ANGLE` — a first-person framing string (only his hand/forearm in the
  lower foreground holding hers, her facing the camera at arm's length, no other
  person's body or face in frame).
- Rides `PhotoRequest.angle`, which `_shot_variant` returns verbatim, so it
  overrides the shot framing **only for dates** — the shared `SCENES` dict and the
  ordinary photo menu are untouched.
- Wired into both reward paths: the Mini App date action
  (`_webapp_media_scene(..., date.scene, dates_service.DATE_POV_ANGLE)`, whose new
  optional `angle` param flows into `PhotoRequest(scene=scene, mood='romantic',
  angle=angle)`) and the bot `_deliver_date_reward`
  (`PhotoRequest(scene=date.scene, mood='romantic', angle=dates_service.DATE_POV_ANGLE)`).

## Uncensored studio leg (`services/webapp_service.py` + `main.py`)
- Root cause of the studio 422: fal Seedream is censored and answers
  `HTTP 422 content_policy_violation` on an explicit prompt (same behaviour the
  «Наедине» nude flow already routes around); the mandatory
  `PICTURE_PROMPT_SUFFIX` («fully clothed … no nudity») also fought the prompt.
- `picture_final_prompt(prompt, style, fmt, adult=False)`: an adult render swaps
  the SFW tail for a quality-only `PICTURE_PROMPT_SUFFIX_ADULT`.
- `_webapp_api_picture_generate`: `adult_ok = is_adult_confirmed(telegram_id)`;
  adult renders ride the uncensored `generate_private_photo_t2i(final_prompt)`
  (SpicyAPI text-to-image) first, falling back to the existing
  `generate_custom_avatar` chain only when that returns nothing. Non-adult users
  keep the exact previous SFW path.
- The hard minors/coercion filter (`picture_prompt_allowed`) still runs **before**
  any adult routing, so those prompts never reach any engine regardless of mode.

## Tests
- New: `tests/test_v3512_date_pov_studio_nsfw_static.py` (6 tests — POV angle
  defined + no second person, `_shot_variant` honours a requested angle verbatim,
  `_webapp_media_scene` threads `angle`, both date paths pin the POV angle while
  the chat-media menu stays default, the adult prompt builder drops the SFW tail,
  and the studio routes adult to `generate_private_photo_t2i` after the block filter).
- Updated pins for the changed signatures: `test_v3410` (media_scene signature +
  date caller), `test_v34417` (media_scene signature), `test_v3380` (final_prompt
  adult arg + uncensored engine), `test_v317_apartment_gifts_dates` (bot date
  PhotoRequest angle), `test_v3437` (scene PhotoRequest angle).
- Full suite: 17 failed / 939 passed / 1 error — exact baseline parity (+6 = the
  new file; the 17 + error are pre-existing and unrelated).

## Deploy notes
- No schema change. `is_adult_confirmed` and `generate_private_photo_t2i` already
  exist; the studio simply gains a conditional route.
- The uncensored studio leg needs `SPICYAPI_KEY` configured (as the «Наедине» nude
  flow already does); without it the adult render falls through to the SFW chain
  and a still-explicit prompt may again surface a provider error to admins only.
- `VERSION` not bumped (3.5x line).
