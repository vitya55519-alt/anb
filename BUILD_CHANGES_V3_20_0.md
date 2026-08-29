# BUILD CHANGES V3.20.0 — retention & monetization pack

Owner request: photo animation for 50 Stars, 2 free daily animations on
Premium, plus every retention mechanic discussed (hooks to keep users glued
to the bot and convert them to Premium).

## Pricing

- `VIDEO_COST_STARS` default 5 → **50**. Existing Railway env overrides win —
  delete/adjust `VIDEO_COST_STARS` there if it is set.
- `VIDEO_PREMIUM_FREE_DAILY` default 1 → **2** free animations/day on Premium
  (shared with circles). Full Stars invoice + auto-refund on failure unchanged.
- `/premium` pitch and the purchase confirmation updated accordingly.

## Retention mechanics

- **Pleasure block, not feature block**: `FREE_MESSAGES_PER_DAY` default
  80 → 20. On limit hit she now "falls asleep" (random in-character texts)
  instead of a dry limit notice; admins are exempt. Both voice and text
  entries use the new `_sleep_block_reply`.
- **Demo premium (3h, one-time)**: `services/retention_service.py`
  `grant_demo_premium` creates a real `Subscription` row (charge marker
  `demo:<uid>`), so every existing premium check picks it up. Offered by the
  first sleep block via «🎁 Демо-Premium» button (`retention:demo`).
- **One-time 24h discount (−30%)**: opens automatically after the demo is
  spent (`User.discount_offered_at`, auto-migrated). Shown with a live
  countdown on the paywall and sleep block; invoiced as
  `premium_month_discount` (own pre_checkout + successful_payment paths).
- **Emotional reminders / jealousy / cliffhangers**: scheduler first tier
  now fires after `RETENTION_REMINDER_HOURS` (24h) with cheap static texts —
  unfinished-conversation cliffhanger if a `pending_hook` exists, jealousy
  for streaks ≥ 3, otherwise "I miss you". The LLM-crafted nudge still fires
  after `PROACTIVE_MIN_HOURS` (48h).
- **Morning/evening rituals**: new `_rituals` job (every 30 min) — she writes
  first in the user's local time window (7–10 / 21–23 by default), only to
  users active in the last 7 days, once per kind per day, with the streak
  ("не прерывай серию") appended.
- **Streaks**: already existed (rewards at 3/7/14/30, achievements, profile);
  now surfaced in rituals. No schema change.
- **Progression plateau**: level-6 non-premium users get the "дальше только
  для премиума" line in the paywall pitch.
- **Premium-exclusive circles (Telegram video notes)**: «🎥 Кружочек от неё»
  button; free users hit the paywall only. Premium users spend the daily free
  slots, extras invoice like an animation (`circle` payload). Delivery is a
  `send_video_note` with graceful fallback to a normal video; auto-refund on
  total engine failure.

## Files

- `config.py`, `models/app_models.py` (discount_offered_at), `services/payments.py`,
  `services/retention_service.py` (new), `services/scheduler_service.py`, `main.py`.
- `tests/test_v3200_retention_static.py`: pins pricing, sleep block, demo,
  discount flow, circles exclusivity, scheduler tiers/rituals, pitch wording.
