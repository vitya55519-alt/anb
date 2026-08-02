# Anna human-chat v2

Implemented on the latest `WaifuBOT-dev(1).zip` source.

## Added
- Human-style response layer: shorter/variable replies, less question-ending, slang, reactions, opinions, topic changes.
- Persistent character state: mood, energy, affection, playfulness, irritation, current activity/topic and pending hook.
- Long-term memory facts in `tb_memory_facts` plus improved conversation summaries.
- Six relationship stages (0/10/50/200/500/1000 message thresholds).
- Automatic language-style detection for common scripts/languages and adaptation instructions.
- Proactive messages with memory/state context; default inactivity window changed to 12 hours.
- Reminder/wake scheduler with repeated wake-up nudges and stop-on-response behavior.
- `/wake HH:MM` and `/timezone IANA/Zone` commands.
- Natural wake/reminder phrase detection inside normal chat.
- Natural photo requests: words such as photo/selfie/picture/foto can trigger the existing image generator without requiring `/selfie`.
- Photo prompt changed from anime/illustration to realistic smartphone photography and now treats appearance text as a stable identity profile (face, eyes, hair, body proportions).
- `/relationship_test N` for admin-only relationship-stage testing. Configure `ADMIN_TELEGRAM_IDS` in `.env`.
- Reset now clears chat summaries, memory facts and reminders.
- New DB tables are created automatically by the existing `Base.metadata.create_all()` mechanism; no manual migration file is required.

## Important image note
The current generator remains DALL-E 3. The new prompt improves consistency from the stored text appearance profile, but DALL-E 3 does **not** provide a hard identity lock from multiple reference photos in this implementation. Exact face/body preservation will require a reference-image-capable provider later.

## Environment additions
```env
PROACTIVE_MIN_HOURS=12
DEFAULT_TIMEZONE=UTC
ADMIN_TELEGRAM_IDS=123456789
```
