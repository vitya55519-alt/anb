# BUILD CHANGES V3.19.5 — Gemini/Veo video restored, Gemini photos hardened

Owner decision: Gemini/Veo video quality is the product standard — it returns
as the PRIMARY video engine (it was briefly removed in v3.19.4). Replicate
(hailuo), fal.ai and the free HF spaces remain as the automatic fallback
chain. Nothing is lost from v3.19.4: the Replicate model upgrade
(`minimax/hailuo-2.3-fast` default) and the model-agnostic input mapping
stay in place as the first fallback.

## Video
- `services/gemini_video_service.py` restored (Veo `predictLongRunning`).
- Engine chain is again **Gemini/Veo -> Replicate -> fal.ai -> HF spaces**.
- `GEMINI_VIDEO_*` settings are back in `config.py`, now gated on
  `GEMINI_API_KEY_VALID` (the v3.19.3 key check) — a dirty-pasted key can no
  longer poison video; the chain silently falls through to Replicate.
- Admin diagnostics restored: the video-unavailable alert lists the Gemini
  key state again; `/geministatus` shows the Gemini Video line.

## Photos (Nano Banana / Gemini image)
- One automatic retry on transient failures: timeouts, transport errors and
  HTTP 408/429/5xx are retried once after a 2s pause before the provider is
  marked failed. This converts many one-off "фото сейчас не получилось"
  moments into delivered photos without touching the fallback chain.

## Railway
`GEMINI_API_KEY` must be a clean ASCII paste (no quotes, spaces or Cyrillic
lookalikes) — then Gemini photos AND video light up automatically.
`REPLICATE_API_TOKEN` stays configured as the fallback engine.

## Tests
- New `tests/test_v3195_gemini_video_restored_static.py` (5 tests).
- `test_v3194_replicate_first_video_static.py` deleted (superseded).
- Pins restored in test_v312, test_v3151, test_v3157, test_v3164,
  test_v3165, test_v3166, test_v3193.
