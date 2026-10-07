# V3.56.0 — Stop the invisible SpicyAPI cannon, make the feed honest, reset Premium

## Symptom (owner)
The SpicyAPI console drained **$1.75 → $0.06** in one hour — jobs at $0.0345
every 1–2 minutes from **15:01 to 16:05 MSK** — while the bot's own admin stats
reported only `картинки $0.080`. The owner looked at the «Генерации
пользователей» feed and saw essentially only his own generations: the money
being burned was not visible anywhere.

## Root cause
1. **The daily-gift cannon.** `services/scheduler_service.py::_daily_gift` fires
   on a `cron hour=12` = **12:00 UTC = 15:00 MSK** — the exact burn window. It
   picked up to **50 users** and called `private_photo_service.send_daily_gift`,
   which rendered a **fresh paid SpicyAPI image per recipient**
   (`generate_private_photo_real`, ~70 s each → 50 renders ≈ 64 min). ≈ **$1.70
   every day**, automatic, nobody asked for it.
2. **Blind accounting.** `_spicyapi_render` never called
   `spend_service.record_image_spend`, so no intimate render (Наедине / косплей /
   adult studio) ever hit the money ledger. `/stats` only ever saw fal/Gemini —
   hence the «$0.080» lie while the real daily spend was ~$3–4.
3. **Double billing.** The adult studio path in `_webapp_media_hot` tried
   `spicyapi_t2i` → on failure `spicyapi_i2i` → then fal: **two paid SpicyAPI
   jobs** on one failed request (and i2i drags a nude back toward the clothed
   reference anyway).
4. **Feed blind spots.** `_daily_gift` and the Telegram «наедине»/косплей button
   handlers (main.py `private_photo_generate`, `private_cosplay_generate`) never
   wrote a `UserGeneration` row — only app-initiated renders appeared.

## Fixes
1. **Gift is free now.** `send_daily_gift` serves the photo **only from the
   owner's free media pool** (`retention_features_service.random_proactive_photo`);
   empty pool → no photo, never a paid render. The gift date is stamped only
   after a successful send. `_daily_gift` now targets only opted-in users active
   within `RITUAL_MAX_INACTIVE_DAYS`, cap trimmed **50 → 15**, and a
   `TelegramForbiddenError` branch marks blocked users (reuses V3.55.9
   `_mark_blocked`).
2. **Honest SpicyAPI ledger.** New knob `SPICYAPI_ESTIMATED_COST_USD`
   (default **0.0345**). `_spicyapi_render` records one `record_image_spend` row
   on the **createTask** event — the true money commit point — with the real
   success flag, so billed failures count too. A `scene` argument is threaded
   from both wrappers (`request.category`, `nude_t2i`). Missing key / no-taskId
   return before the ledger (never charged).
3. **Single paid attempt.** The adult path is now `spicyapi_t2i → fal t2i`; the
   `spicyapi_i2i` re-bill is gone.
4. **Everything is auditable.** `UserGeneration` gains `engine` / `cost_usd`
   columns (auto-migrated). `record_generation` carries them; the admin feed
   endpoint returns per-row engine+cost and a `spent_today_usd` header sourced
   from `spend_service.image_cost_today()`. `_webapp_media_hot` stashes its true
   engine/cost in `_HOT_MEDIA_HINT` (cache/pool = $0, spicyapi/fal = real) so the
   upstream recorder labels hot/cosplay rows accurately. Both Telegram private &
   cosplay buttons now write feed rows. The Mini App feed renders
   «💸 сожжено на картинки сегодня: $X» and a per-row `· engine · $cost`.
5. **Premium reset.** All Premium grants in this build are test/admin. New
   `payments.revoke_all_premium()` cancels every live subscription in one shot
   (history and photo credits untouched), exposed as the admin-only Telegram
   command **`/revoke_all_premium`**.

## Expected effect
- the 15:00 MSK gift cannon stops spending entirely (pool-only, ≤15 active);
- `/stats` «картинки» now includes SpicyAPI — the real number, failures counted;
- a failed adult studio render costs $0.0345, not $0.069;
- the owner can see **who** generated **what**, on **which engine**, for **how
  much**, including the previously-invisible gift and Telegram-button paths;
- one command clears all test Premium.

## Tests
- `tests/test_v3560_spicy_money_premium_static.py` — 12 static checks: cost knob,
  render-ledger ordering (no bill before createTask), scene threading, gift
  pool-only + stamp-after-send + audit, active-only/403/cap-15, single spicy
  attempt on the adult path, `_HOT_MEDIA_HINT` cache/pool/spicy labels,
  record_generation engine/cost, Telegram button audits, endpoint daily burn,
  feed HTML money line, new model columns + migration, and the admin-gated
  `revoke_all_premium`.
- Full suite: 16 failed / 1054 passed / 1 error — exact baseline parity
  (1042 + 12 new), all failures pre-existing content drift.

## Files
- `config.py` — `SPICYAPI_ESTIMATED_COST_USD`
- `models/app_models.py` — `UserGeneration.engine`, `.cost_usd`
- `services/db.py` — `user_generations` column migration
- `services/private_photo_service.py` — spend ledger in `_spicyapi_render`,
  scene args, pool-only `send_daily_gift`
- `services/scheduler_service.py` — `_daily_gift` active-only + cap 15 + 403
- `services/webapp_service.py` — `record_generation` / `list_generations` engine+cost
- `services/payments.py` — `revoke_all_premium()`
- `main.py` — `/revoke_all_premium`, adult single-attempt, `_HOT_MEDIA_HINT`,
  Telegram private/cosplay audits, endpoint `spent_today_usd`
- `webapp/index.html` — feed shows engine/cost + daily burn header
- `tests/test_v3560_spicy_money_premium_static.py` — new
