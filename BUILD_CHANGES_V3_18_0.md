# BUILD CHANGES v3.18.0

## Relationship system upgrade

The relationship system felt flat: progress was invisible, level-ups were
silent, keyword-only signals ignored real conversation quality, and gifts
moved an axis that did not unlock levels. This release addresses all four.

### Level-up ceremony
- `services/relationship_service.py`: new `set_stage_change_notifier(fn)`
  registry. On any upward stage change (chat, gifts, dates, apartment) the
  notifier fires as a background task.
- `main.py`: `_on_relationship_stage_up` — waits 3s so her chat reply lands
  first, then announces the new stage («❤️ Между нами что-то изменилось…»),
  lists fresh unlocks (photo scenes, apartment rooms, dates gated at that
  level) and sends a small celebration photo set (scene `selfie`, story
  delivery). Tracked via `relationship_ceremony_sent`.

### Visible progress
- Profile card now shows `💞 Характер связи` and per-axis progress bars
  (`📈 До следующего этапа:` ❤️/🤝/🔥 `▓▓▓░░░░░ 42/55`) toward the next
  stage, computed with the same effective-axis math as the stage gates.
- New engine helpers: `bond_character()`, `next_stage_progress()`,
  `progress_bar()`.

### Instant feedback
- The text handler sometimes (30%) reacts with ❤️ to messages that carried a
  care/flirt signal, so the user feels the bond moving in real time.

### LLM relationship pulse
- New `services/relationship_pulse.py`: every 8 user messages, the chat LLM
  scores the recent excerpt (`warmth`/`trust`/`intimacy` 0–3 + events like
  `callback`, `inside_joke`, `meaningful_share`) and applies a small extra
  delta (axis × 0.4). Events map onto the engine's connection-boosting types,
  so quality talk finally grows the hidden dimensions. Fail-silent; flag
  `RELATIONSHIP_PULSE_ENABLED` (default true).
- Wired in `chat_service.reply` as a background task (test mode excluded).

### Personalization
- `bond_character()` derives the bond flavor from the leading axis —
  страстный роман / глубокое доверие / лёгкий флирт / гармоничная близость —
  shown in the profile and appended to the chat relationship context so her
  tone matches.

### Reconnect moments
- Returning after 3+ days of silence now adds +1.5 connection in the engine,
  and the chat context tells her she may warmly notice the return.

### Gift balance
- Gifts now also grow trust: `trust = max(0.5, affection × 0.25)` on both the
  paid and admin-test paths, so paid affection feeds the trust gate that
  levels actually check.

## Tests
- New `tests/test_v318_relationship_upgrade_static.py`: 10 tests — ceremony
  wiring, profile progress/bond, reaction, pulse service + parser runtime,
  reconnect bonus, gift trust, and runtime checks for `bond_character`,
  `next_stage_progress`, `progress_bar`.
