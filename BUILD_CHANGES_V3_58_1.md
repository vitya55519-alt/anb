# V3.58.1 — date button that always answers, studio stops waiting on dead engines

## Date («Свидание»)
- Before: tapping a place (e.g. «Кофейня») waited for the narration **and** the scene photo in one request. The photo chain can take minutes, so the Mini App looked frozen and nothing reached the chat.
- After: the narration is saved and returned at once; the photo is generated in the background (`_deliver_date_photo`) and lands in the chat as «📸 фото с нашей прогулки».
- SPA: the panel closes immediately, a typing bubble «Собирается на свидание… 💕» shows, double taps are ignored (`featBusy`), and `waitForDatePhoto` polls the chat until the photo arrives.

## Studio / photo engines
- SpicyAPI circuit breaker per leg (`model:edit` / `model:t2i`): 3 failures in a row → skip that leg for 15 min instead of burning up to 90s each time.
- Spicy sets stop early when the breaker is open (returns frames already made, or fails fast).
- Gemini image: after HTTP 429 it is skipped for 30 min (`GEMINI_429_COOLDOWN_SECONDS`).

## Tests
- New `tests/test_v3581_date_and_breakers.py`; two static pins updated for the new wrapper/raise.
