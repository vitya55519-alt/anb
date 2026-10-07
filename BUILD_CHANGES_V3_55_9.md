# V3.55.9 — Proactive throttle: stop burning the LLM budget on ghosts

## Symptom (owner: «вовлеченность ужас»)
Admin stats 07.10: D1 3% / D7 1%, 6 daily actives — but
`LLM по задачам: proactive $2.489 / 3302 вызова` vs `dialogue $0.101 / 111`.
96% of all LLM spend went to proactive messages that mostly nobody received.

## Root cause
In `services/scheduler_service.py::_proactive` (hourly scan) the nudge stamp
(`CharacterState.last_nudge_at / nudge_count`) was written **only after a
successful send**. Every failed `bot.send_message` — and for a 290-user base
most of the inactive crowd has blocked the bot or deleted the account — raised
before the stamp, so the same user was picked up again the next hour and
consumed another `proactive_reply()` LLM call. Forever. The V3.44.16 ladder
(interval + max-5 cap) never engaged because its counters were never persisted
for failing users. Same retry-forever shape existed in `_reminders` (30-min
loop), `_day1_hook` (15-min loop), `_rituals` and `_life_events` (the latter
already spent its slot pre-send, but kept paying 403s).

## Fixes
1. **Stamp before spend** — the nudge slot is consumed inside the read session,
   before the static/LLM tier runs. A failed send now costs one slot, not an
   hourly re-fire. (Keeps every V3.44.16 ladder pin intact.)
2. **Ghost window** — new knob `PROACTIVE_MAX_INACTIVE_DAYS` (default 10,
   clamp 3–30): users silent longer than that are treated as churned and drop
   out of the `_proactive` SQL entirely. A real return re-arms the ladder.
3. **403 = blocked** — `TelegramForbiddenError` gets a dedicated branch in
   `_proactive`, `_reminders`, `_day1_hook`, `_rituals`, `_life_events`:
   `_mark_blocked(uid)` flips `proactive_enabled=False` (never auto-re-enabled —
   the in-chat settings toggle is the only way back, so real opt-outs are
   respected), reminders are dropped, day-1/ritual slots are burned.
4. **Empty LLM reply** no longer sends an empty message (which used to raise
   and re-arm the retry); the spent slot is logged instead.

## Expected effect
- proactive spend $2.49/day → cents/day (only reachable, recently-active users
  get LLM nudges, max 1/user/day, ≤5 per silence cycle);
- no more silent spam-flooding of blocked accounts (API call saving + no
  accidental report buttons);
- retention ladder for genuinely win-backable users stays alive (it was the
  V3.44.16 goal) — just no longer screaming into the void.

## Tests
- `tests/test_v3559_proactive_throttle_static.py` — 5 static checks: ghost
  knob + SQL filter, stamp-before-send ordering (single stamp block), empty
  reply skip, 403 branches in all five jobs + helper semantics, and a
  regression pin that the V3.44.16 ladder lines survived the refactor.
- Full suite: 16 failed / 1042 passed / 1 error — exact baseline parity
  (1037 + 5 new), all failures pre-existing.

## Files
- `config.py` — `PROACTIVE_MAX_INACTIVE_DAYS`
- `services/scheduler_service.py` — `_mark_blocked()`, `_proactive` rewrite,
  403 branches in `_reminders` / `_day1_hook` / `_rituals` / `_life_events`
- `tests/test_v3559_proactive_throttle_static.py` — new
