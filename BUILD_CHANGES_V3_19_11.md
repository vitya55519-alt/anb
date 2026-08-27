# BUILD CHANGES V3.19.11 — auto-applied storefront descriptions (RU + EN)

The bot profile description is the first thing a new user sees in the profile,
in catalogs and in shared links. To maximize audience reach it is now written
in code and applied automatically on every startup for two locales:

- default (English) — global audience;
- `ru` — Russian-speaking audience.

## Content

Both descriptions pitch the core hooks (flirty unscripted chat, photos on
request, videos & voice notes, morning wake-ups, gifts/dates/quests, three
heroines Anna/Emily/Maria, "she remembers you"), stay within Telegram limits
(description <= 512, short <= 120) and carry the required `18+` marker.

## Changes

- `services/bot_description.py` (new): `DESCRIPTION_DEFAULT/RU`,
  `SHORT_DESCRIPTION_DEFAULT/RU`, `apply_bot_descriptions(bot)` calling
  `set_my_description` / `set_my_short_description` per locale.
- `main.py`: startup calls `apply_bot_descriptions(bot)` after the web server
  starts and before polling; wrapped in try/except so a Bot API failure never
  blocks startup.
- `tests/test_v31911_bot_description_static.py`: limit + 18+ pins, feature
  pitch pins, startup wiring pins.
