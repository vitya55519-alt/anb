# Build Changes — v3.17.0

## New: Apartment, Gifts and Dates

Three engagement features added to the main menu: квартира, подарки, свидания.
All are gated by relationship level and wired through the existing Telegram
Stars payment flow (`pre_checkout` amount validation + `successful_payment`).

### `services/apartment_service.py` (new)
- 4 rooms (гостиная/кухня/спальня/ванная) with `min_level` 1–4 gating.
- Each room has actions (пообщаться, фильм, кофе, ужин, отдых, интим, душ, ванна);
  every action returns her reply + small relationship/intimacy deltas.
- APIs: `get_available_rooms`, `get_locked_rooms`, `get_room`, `room_action_reply`.

### `services/gifts_service.py` (new)
- 6 gifts (3–20 Stars) with affection deltas and per-gift reactions.

### `services/dates_service.py` (new)
- 7 dates (5–15 Stars) gated by level 1–5; each ends with a reward photo set
  generated from the date scene (`cafe`, `park`, `cinema`, `embankment`,
  `restaurant`, `rooftop`, `club`).

### `main.py`
- **Keyboard**: added `🏠 Квартира` / `💕 Свидание` row and `🎁 Подарить`
  next to `🔗 Пригласить`; `abilities_text` lists the new features.
- **Handlers**: apartment menu + room entry (room resolved by id with level
  gate), room actions with relationship deltas (`record_user_message`),
  gifts menu + Stars invoice, dates menu + Stars invoice with level gate.
- **`pre_checkout`**: validates `gift:` / `date:` payloads against catalog
  costs; dates also re-checked against the buyer's current relationship level.
- **`successful_payment`**: gift branch records payment, applies affection,
  sends her reaction; date branch records payment, applies affection/intimacy,
  sends the date narration and starts a `story` photo set from the date scene.

### Notes
- Video part of the original plan (Replicate i2v, Stars refund on failure)
  is already live since v3.16.6 (`cloud_video_service`, engine chain
  Gemini → Replicate → fal.ai → HF) — no changes needed.

### `VERSION`
- Bumped to `3.17.0`.
