# Anna repair — 2026-08-03

This build keeps the existing project structure and fixes the broken routing between
Telegram and the newer Anna character stack.

## What changed

- Telegram normal text chat now uses `services.chat_service.reply()`.
- Voice chat now uses the same Anna engine after transcription.
- `/start` no longer forces the old Spanish configuration flow.
- Anna is initialized immediately with the user's Telegram first name.
- Legacy configuration commands remain available for compatibility.
- The old MySQL-only connection path now uses `DATABASE_URL` and falls back to local SQLite.
  This prevents `localhost:3306` failures during local development.
- Added missing character/database/image/TTS/payment settings to `config.py`.
- `services.chat_service` now uses the canonical service `User.id` consistently for messages and memories.
- Proactive messages now use Anna's character profile, relationship state and memory instead of the old Spanish prompt.
- `.gitignore` excludes local databases, Python cache files, secrets and ZIP archives.

## Important

Set `DATABASE_URL` in Railway to the database connection URL provided by Railway.
For local testing, the default is `sqlite:///./waifubot.db`.

The canonical Anna profile is `data/characters/anna.json`.
