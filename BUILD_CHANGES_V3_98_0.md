# V3.98.0 — engagement pack after the 3 Nov 2026 stats review

Backup 2026-11-03 00:30: 92 newcomers of 26–31 Oct wrote at least once, 18 came back
on another day, 78 lived exactly one day. Those who wrote 20+ messages on day one
came back at 27%, 50+ at 37%.

- Language (services/lang_guard.py): 207 of 1475 replies to English messages (14%),
  71 of 107 English users, came back in Russian. Now an English message gets a system
  directive right before it, and a Cyrillic answer is regenerated once with a firm one.
- «Her» girl: after accepting 18+ a new user without a saved choice gets a picker
  (Girl of the day, Агата, Анна, Алиса, Камила, Рита). A tap saves the choice and
  sends her hello + welcome selfie. If he ignores it, the default hello goes out after
  2 minutes. Events `girl_picker_shown`, `girl_picked`.
- Failed chat photo (31 «фото не загрузилось» a week): the app chat sends a ready photo
  of her (pool or past render, never spicy) for free, without using the day's allowance.
  Event `photo_fallback_pool`.
