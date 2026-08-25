# BUILD CHANGES V3.19.3 — Broken Gemini Key Isolation + Hardened Fallback Chains

Production incident: a `GEMINI_API_KEY` pasted with non-ASCII characters
surfaced as `фото сейчас не получилось (gemini_image/invalid_api_key_non_ascii)`
and poisoned the Gemini/Veo video engine too, while both engines still
reported READY at startup.

## 1. Broken-key gate (`config.py`)
- New `GEMINI_API_KEY_VALID`: key must be non-empty, pure ASCII and
  whitespace-free. A broken key is now treated as absent:
  - `GEMINI_IMAGE_ENABLED` and `GEMINI_VIDEO_ENABLED` require a valid key,
    so photo/video routing skips straight to the next engine instead of
    failing with an opaque auth error.
  - Loud `CONFIG WARNING: GEMINI_API_KEY contains non-ASCII or whitespace...`
    line at startup (visible in Railway logs).

## 2. Chat fallback gated (`llm_provider_service.py`)
- The Gemini chat-fallback client is only built for a valid key;
  `provider_status` reports `gemini_key_present` accordingly.

## 3. Hardened photo fallback chains (`photo_service.py`)
- Seedream route: each fallback engine (Gemini → OpenAI → Pollinations) is
  wrapped in its own try/except; the chain only raises after ALL engines
  failed (`raise last_error`). Previously the first failing fallback
  (e.g. the broken Gemini key) killed the photo.
- Gemini route: a failing OpenAI fallback now still hands over to Seedream.

## 4. Diagnostic wording (`main.py`)
- The admin "video unavailable" checklist now says
  "❌ нет/битый GEMINI_API_KEY (должен быть чистый ASCII)".

## Action required on Railway
Re-paste `GEMINI_API_KEY` cleanly (no quotes/spaces/Cyrillic lookalikes),
then redeploy. Photos will fall back to OpenAI/Pollinations meanwhile;
video uses Replicate/fal.ai/HF until the key is fixed.

## Tests
- New `tests/test_v3193_gemini_key_gate_static.py` (5 tests).
