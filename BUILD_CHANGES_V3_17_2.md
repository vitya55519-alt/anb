# BUILD CHANGES v3.17.2 / v3.17.3

## Bug fixes

### 1. Lingerie no longer renders on top of the outfit
Production evidence showed the image model drawing the bra and panties OVER
the top/jeans. Root causes and fixes in `services/photo_service.py`:

- **Level rules rewrote themselves against us**: every `LEVEL_UNDERLAY_RULES`
  entry (levels 1–6) asked for lingerie to be "clearly but subtly visible" /
  "intentionally visible". Image models cannot layer garments, so "visible"
  became "worn on top". Every rule now explicitly forbids underwear as
  outerwear (`never on top of it`) and allows at most a through-fabric
  outline or a lace edge at the neckline.
- **Visibility-detail injection removed**: the v3.17.1
  `UNDERWEAR_VISIBILITY_DETAILS` pool ("a bra strap slipping visibly onto her
  shoulder", ...) was the strongest over-rendering trigger. Removed entirely.
- **Underwear color/style is named only where lingerie is meant to be seen**:
  level 5+ or private/peek/dressing scenes. In ordinary low-level shots the
  prompt no longer names the bra/panties at all.
- **NEGATIVE_BLOCK** now lists "underwear worn over the outfit: bra over the
  top, panties over jeans or any lingerie as outerwear".

### 2. Video pipeline reliability + diagnostics
- `services/cloud_video_service.py`: Replicate no longer uses
  `replicate.run(wait=600)` — the API caps the Prefer-wait window at ~60s, so
  `run()` returned an unfinished prediction with no output and the job fell
  through to the flaky HF spaces. The engine now creates the prediction
  explicitly and polls `prediction.reload()` every 5s up to
  `REPLICATE_VIDEO_TIMEOUT_SECONDS`, raising precise errors
  (`replicate_timeout:<status>`, `replicate_failed:<detail>`).
- `main.py` `_run_video_background`: collects every per-engine failure and,
  for admins, reports the full chain (`движки: ... / цепочка: gemini: ... |
  replicate: ... | hf: ...`) instead of only the last error.
- `/geministatus` now shows Replicate and fal.ai availability in addition to
  Gemini Video and HF Video.

## New features (engagement batch 1)

### 3. Gift of the day (−30%)
- `services/gifts_service.py`: `DAILY_DISCOUNT = 0.30`,
  `get_daily_featured()` (deterministic rotation by date),
  `is_featured()`, `effective_cost()`.
- `main.py`: 🎁 Подарить catalog marks the featured gift with 🔥 and the
  discounted price; invoice and `pre_checkout` validation both use
  `effective_cost()` so discounted purchases pass verification.

### 4. Voice replies after gifts and dates
- `_send_voice_note()`: after a gift or date she also answers with a voice
  message (only when the user has voice replies enabled; emojis stripped for
  natural TTS).

### 5. 7-day streak → free date
- `services/gamification_service.py`: `FREE_DATE_STREAK = 7`, vouchers stored
  as 0-star payment markers (`free_date_grant` / `free_date_used`, idempotent
  via the unique charge marker — no schema change). `has_free_date()` /
  `consume_free_date()` helpers.
- `main.py`: 💕 Свидание shows a banner while a voucher is available;
  starting any available date consumes the voucher instead of sending an
  invoice. Date reward delivery was extracted into `_deliver_date_reward()`
  shared by the paid and free paths.

### 6. Date collection + engagement achievements
- `gamification_service.completed_date_ids()` reads completed dates from
  `date:*` relationship events; the 💕 Свидание menu marks completed dates
  with ✅ and shows a collection counter.
- New achievements: `first_gift`, `first_date`, `ten_dates`, `date_collector`
  (wired into the gift and date reward paths).
- New premium gift: 🛥 Прогулка на яхте (50⭐, +10.0 affection).

## v3.17.3 — Admin test mode for paid features
- Admins (`ADMIN_TELEGRAM_IDS`) can now click any gift or date and get the
  full flow instantly — relationship delta, her reply, voice note, reward
  photo set — without a Stars invoice and without consuming the free-date
  voucher. Tracked as `admin_test_gift` / `admin_test_date`.
- Level-gated content (apartment rooms, dates, photo scenes) is already
  testable via the existing `/testlevel 1..6` override (`/testlevel off` to
  reset); the video pipeline has `/videotest`.

## Tests
- Updated: `test_v31611_underwear_underlay_static.py` (new under-layer
  framing + color gating + per-level layering guard),
  `test_v3165_maria_video_variety_static.py` (re-pinned level-1 rule),
  `test_v3171_underwear_visibility_static.py` (visibility pool removal).
- New: `tests/test_v3172_engagement_static.py` — Replicate polling, admin
  chain diagnostics, gift-of-day wiring, voice notes, free-date voucher.
