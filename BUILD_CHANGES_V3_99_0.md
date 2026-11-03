# V3.99.0 — open loop (services/open_loop.py)

Backup 2026-11-03: 78 of 92 newcomers lived one day; 20+ messages on day one → 27% came back.

- After 15 of his messages in 6 hours (env OPEN_LOOP_AFTER_MESSAGES) she has to go: she hints at
  ONE specific thing she wanted to tell/show/confess and promises it for tomorrow morning.
  Not for Premium (they pay for a chat that does not end), serious/task talk, scenes, or
  within OPEN_LOOP_COOLDOWN_DAYS (3) of the last loop. Env OPEN_LOOP_ENABLED=false turns it off.
- For the next 14 h she dodges «ну скажи!» instead of revealing the secret.
- The morning ritual (chat_service.morning_callback) keeps the promise: it gets her own line and
  reveals the thing, then asks a hooking question.
- Events: open_loop_shown, open_loop_planted (carries her line), open_loop_kept, open_loop_kept_sent.
  The morning only reaches people with rituals on; others never get the keep.
