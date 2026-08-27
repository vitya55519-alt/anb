# BUILD CHANGES V3.19.9 — Pollinations removed, paid providers only

The free Pollinations.ai fallback kept returning `http_500` and had previously
produced wrong-subject renders. On the owner's request it is removed
completely; the photo pipeline now uses only the paid/configured providers.

## Photo chain after removal

- Intimate/private scenes: fal.ai Seedream 4.5 (primary).
- Ordinary scenes: Gemini Image (primary) -> OpenAI (fallback).
- Cross-engine fallbacks remain: Seedream -> Gemini -> OpenAI,
  Gemini -> OpenAI -> Seedream, OpenAI -> Gemini -> Seedream.
- If no provider is configured, the ultimate fallback is Seedream.

## Changes

- `services/photo_service.py`: deleted `_run_pollinations_set`,
  `_pollinations_one_frame`, the `provider == 'pollinations'` dispatch branch,
  all `to=pollinations` fallback legs, `POLLINATIONS_*` imports and the
  now-unused `urllib.parse.quote` import. Provider log line no longer lists
  Pollinations.
- `config.py`: removed `POLLINATIONS_ENABLED`, `POLLINATIONS_MODEL`,
  `POLLINATIONS_TIMEOUT_SECONDS`, `POLLINATIONS_WIDTH`, `POLLINATIONS_HEIGHT`
  and `POLLINATIONS_MAX_PROMPT_CHARS`.
- `.env.example`: removed the Pollinations block.
- Safety kept: `ADULT_ONLY_LOCK` (HARD SUBJECT LOCK, adult woman 20+, never
  minors) stays in every provider prompt right after the identity block.
- Tests: deleted `test_v315_pollinations_free_fallback_static.py`; repinned
  `test_v3193`, `test_v3192`, `test_v3181`; `test_v3197` now also asserts the
  provider is absent from code and config and that the remaining fallback
  chain is intact.

## Notes for Railway

- No env vars to change: the removed `POLLINATIONS_*` variables are simply
  ignored if still present; they can be deleted from the Railway Variables
  tab at convenience.
- Photo quality now depends on GEMINI_API_KEY / OPENAI_API_KEY / FAL_KEY being
  set — at least one must be present or every photo request will fail.
