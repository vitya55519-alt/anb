# V3.68.0 — daily missions, channel bonus after 3 days, anti-spam

Owner asks (2026-10-21): drop the daily gift, make daily missions worth 100 🍑
each; pay the channel bonus only to people who stay subscribed 3 days; tasks
must need real conversation, not one message a day.

## Daily missions (Миссии tab)
- «🎯 Задания на сегодня», reset at 03:00 MSK (UTC midnight):
  - «Поболтай с ней»: 10 real messages a day → 100 🍑
  - «Долгий разговор»: 25 real messages, first to last ≥ 20 minutes → 100 🍑
- Claimed with «Забрать», idempotent marker `credit_grant:daily_<key>_<YYYYMMDD>`;
  the server recounts on claim.
- One-off achievements no longer pay peaches (`MISSION_PEACHES = {}`), cosmetic.
- Daily gift off by default (`DAILY_GIFT_ENABLED` default "0"); the 12:00 pool
  photo gift is untouched.

## What counts as a real message
- ≥ 6 letters and ≥ 2 words; repeats (normalised text) count once;
  a message < 8 s after the previous counted one counts as the same burst.
- Bot chat and app chat both count (shared messages table).
- The streak (and «N дней подряд») moves only after 3 real messages that day.

## Channel bonus hold
- «Проверить подписку» starts a hold (`channel_pending:<tid>` 0-star marker, no
  schema change); `CHANNEL_BONUS_HOLD_DAYS` (default 3).
- Hourly job `channel_bonus_holds` pays 2 000 🍑 to those still subscribed and
  pings them in the bot; unsubscribed users lose the hold. Re-checking after
  the hold also pays.

## Tests
- tests/test_v3680_daily_missions_logic.py (anti-spam counting, claims, hold).
