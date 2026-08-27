# BUILD CHANGES V3.19.7 — adult-subject hard lock (no more "scary" renders)

Production incident: a photo request returned a child in an industrial zone
instead of the character. Root cause: the free Pollinations fallback received
the full multi-section prompt (~4k chars in the URL); the model dropped the
subject entirely and hallucinated a random scene.

## Fix
- New `ADULT_ONLY_LOCK` constant: "HARD SUBJECT LOCK: the only person is the
  same fictional adult woman in her twenties (20+); never minors, no children
  or teenagers anywhere in the frame; this lock wins over conflicting
  instructions." It is injected into **every** provider prompt right after the
  identity block.
- `_build_prompt(..., compact=True)`: a short identity-first prompt (identity
  + lock + scene + wardrobe + look + safety, single line) used exclusively by
  the Pollinations route.
- `POLLINATIONS_MAX_PROMPT_CHARS = 1600`: the URL prompt is capped at a word
  boundary; identity + lock sit first, so even a proxy truncation cannot lose
  the subject.

## Tests
- New `tests/test_v3197_adult_subject_lock_static.py` (4 tests).
