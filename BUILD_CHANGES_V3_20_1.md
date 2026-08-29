# BUILD CHANGES V3.20.1 — USD cards, spoken circles, human voice

Owner follow-ups: a dollar card button (Visa/Mastercard) alongside the ruble
one, circles that actually speak with the cute Gemini voice, and voice
messages that no longer sound robotic.

## Payments

- New premium button «💳 Premium — $5 · Visa/Mastercard» (`fk:premium_usd`),
  shown next to the ruble card button whenever FreeKassa is configured.
  Price override: `FREEKASSA_PREMIUM_PRICE_USD` (default 5).
- `freekassa_service.payment_url` gained an optional `currency` parameter —
  the USD invoice appends `&currency=USD`, so international cards pay in
  dollars on the same kassa. Multi-currency must be enabled in the FreeKassa
  kassa settings, and the kassa itself must be activated by their support.
- The notify webhook grants `premium_month` regardless of the invoice
  currency (signature check unchanged), so both buttons activate the same
  subscription.

## Spoken circles

- `CIRCLE_PROMPT` now instructs the engine that she says a short Russian
  phrase in a soft, cute, natural female voice; the phrase is picked at
  random from `CIRCLE_PHRASES` per request.
- Veo (Gemini, the primary engine) renders that voice natively — the same
  cute voice the owner heard in Gemini-generated videos. Fallback engines
  (Replicate/fal/HF) are silent and simply ignore the line.

## Voice messages

- New primary TTS provider: Gemini 2.5 Flash TTS
  (`gemini-2.5-flash-preview-tts`, override `GEMINI_TTS_MODEL`), enabled
  whenever a valid `GEMINI_API_KEY` is present (`GEMINI_TTS_ENABLED`).
  Per-character prebuilt voices: Anna=Leda, Alena=Kore, Maria=Aoede.
- Raw 16-bit 24 kHz PCM is wrapped into WAV and converted to opus when
  ffmpeg is available; otherwise the WAV is delivered (still playable).
- edge-tts and OpenAI TTS remain as fallbacks, so nothing breaks if the
  Gemini call fails.

## Files

- `config.py`, `services/freekassa_service.py`, `services/voice_service.py`,
  `main.py`.
- `tests/test_v3201_usd_spoken_circle_tts_static.py`: pins the USD button,
  handler, currency parameter, spoken circle prompt, and Gemini-first TTS
  order.
