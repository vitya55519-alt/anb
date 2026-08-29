# V3.25.0 — avatar engines, reference downscaling, fal transparency, TTS chain

## 1. Constructor avatar: the engines were missing entirely

`generate_custom_avatar` called `_seedream_edit(...)` and `_gemini_edit(...)`,
but **neither function existed anywhere** — every avatar attempt crashed with
NameError and the user saw «аватар сейчас не получился 😕». V3.25.0 implements
both in `services/photo_service.py`:

- `_seedream_edit(reference_path, prompt)` — Seedream v4.5 edit with the
  user's face photo as the identity anchor (face-swap), then downloads the
  result URL and returns bytes.
- `_gemini_edit(prompt, reference_path=None)` — Gemini image
  `generateContent` (text-to-image, optional inline face reference) as the
  fallback and the no-reference route.

## 2. Reference images downscaled before base64 embedding

The canonical reference PNGs are ~5 MB each; every Seedream request embedded
a ~6.6 MB base64 data URI (Gemini frames embedded two of them). New
`_image_b64()` re-encodes oversized references to a compact JPEG (longest
side ≤1280, quality 88, Pillow) with an mtime-keyed cache; `_file_data_uri`
and the Gemini frame loop now route through it. `Pillow>=10.0.0` added to
requirements. This removes the multi-MB payload as a fal HTTP 422 cause.

## 3. fal error bodies now visible in the chat error chain

`_seedream_request` carries a 140-char excerpt of the fal 4xx body inside the
PhotoGenerationError reason, e.g.
`(seedream45/HTTP 422 {"detail":...} → gemini_image/http_400)`.
The clothed safe-retry trigger now matches by prefix
(`exc.reason.startswith(('HTTP 400', ...))`), so enriched reasons still
activate it. If intimate sets still fail after deploy, the chat line itself
will say why (moderation vs validation vs key).

## 4. Human-like voice: TTS model chain

Google superseded `gemini-2.5-flash-preview-tts` with
`gemini-3.1-flash-tts-preview` (recommended replacement). `_tts_gemini` now
walks `_TTS_MODEL_CHAIN` (env `GEMINI_TTS_MODEL` override first, then 3.1
preview, then 2.5 preview), retries once with 2 s backoff on 429/503, and
remembers the last working model in `_tts_good_model`. When Gemini TTS
succeeds the voice notes use the natural Gemini voices (Leda/Kore/Aoede),
not the robotic edge-tts fallback.

## Tests

`tests/test_v3250_avatar_tts_reliability_static.py` — 6 tests. Suite: 360.

## Owner notes

- Railway will install Pillow on next deploy automatically.
- If the spicy set still 422s after deploy, copy the chat error line (it now
  contains the fal body excerpt) — it distinguishes moderation rejection
  from payload/validation problems and from a missing `FAL_KEY`.
- Voice: after deploy, voice notes should sound human again as long as the
  Gemini key is valid; edge-tts remains only as a last-resort fallback.
