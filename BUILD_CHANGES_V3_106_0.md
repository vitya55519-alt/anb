# V3.106.0 — her voice sells: human voice, a free taste, Stars first abroad, «без автопродления»

Backup 05.11: all 3 payments came in the first session; 2 of 3 payers hit the «🔊» Premium wall right
before paying; that wall was hit by 61 people in two weeks. An English user tried SBP and Stars and gave up.

- `services/voice_humanize.py` (`VOICE_HUMANIZE_ENABLED`): chat line → spoken line for Grok TTS with
  speech tags: «хаха»/😂 → [laugh], «)))»/🙈 → [giggle], 😏 → [chuckle], 🥺 → [sigh], «ммм» → [breath],
  «…» → [pause] (max 3 tags), tender lines and soft girls → <soft>, «*шепчу*» → <whisper>; *actions*,
  links, emoji removed. Gemini/edge fallbacks get the same line without tags. Callers pass the raw line
  (`main._tts_text`).
- `services/voice_taste.py` (`VOICE_TASTE_ENABLED`, `VOICE_TASTE_FREE`=2): without Premium her first two
  app-chat replies (from his 2nd message, 12–320 chars) come as voice notes on their own; then once a day
  a «🎙 Слышать её голос всегда» chip (trial-first pay sheet). Events `voice_taste_sent`,
  `voice_taste_offer`, `paywall_view{product: voice_taste}`.
- App pay sheet: for non-Russian UI Telegram Stars lead («bought right in Telegram — Apple Pay / Google Pay
  / card»), crypto next, then card. Under every sheet: «Разовый платёж · без автопродления».
- Bot Platega link message: «Это разовый платёж, без автопродления».
- Tests: `tests/test_v3106_voice_and_pay.py`; pins updated in `test_v3570_voice_photo_static`
  (new gate) and `test_v3740_grok_voice` (soft line).
