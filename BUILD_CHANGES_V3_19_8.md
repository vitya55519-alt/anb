# BUILD CHANGES V3.19.8 — Pollinations rich prompt restored

The v3.19.7 compact-prompt experiment for the free Pollinations fallback
degraded photo quality (owner: "он нормально все делал, ты все испортил").
Reverted to the rich full prompt that produced good photos.

## What stays from v3.19.7
- `ADULT_ONLY_LOCK` (HARD SUBJECT LOCK: adult woman 20+, never minors) is
  still injected into every provider prompt right after the identity block.
- For Pollinations the lock is additionally **prepended at the very start** of
  the prompt, so the subject constraint leads even before the identity text.

## What changed
- `_pollinations_one_frame` sends the full multi-section prompt again
  (identity + scene + wardrobe + look + quality + FREE PROVIDER rule).
- `POLLINATIONS_MAX_PROMPT_CHARS` raised 1600 -> 4000: a generous guard only
  (the endpoint accepts ~9KB URLs); the lock sits first, so even a hard cut
  never loses the subject.
- Removed the now-unused `compact` prompt branch, `ANNA_COMPACT_IDENTITY` and
  the 5-tuple identity return.

## Tests
- `tests/test_v3197_adult_subject_lock_static.py` repinned: lock constant +
  4000 cap, full prompt contains the lock before SCENE, Pollinations block
  keeps the rich prompt with the lock prepended and no `compact=True`.
