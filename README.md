# AnnaBot V3

Telegram AI companion with one canonical architecture for chat, memory, relationship progression, reminders, voice, Telegram Stars payments and reference-based photos.

## Required Railway variables

- `TELEGRAM_TOKEN`
- `OPENAI_API_KEY`
- `DATABASE_URL` (recommended: Railway PostgreSQL; local fallback is SQLite)
- `ADMIN_TELEGRAM_IDS` for `/testlevel`

Useful optional variables are listed in `.env.example`.

## Photo engine

The default image model is `gpt-image-2`. Photos use `images.edits` with an Anna reference image; there is no prompt-only fallback that can silently create a different character. Clothing, location, hairstyle and camera angle may change while the prompt explicitly asks to preserve identity and body proportions.

Reference files are in `data/references/anna/` and selected by requested scene.

## Product behavior

- `/start` starts chat immediately; no setup wizard.
- `/photo` opens scene presets.
- Natural photo requests such as “покажись”, “сделай селфи”, “фото в парке” are recognized in chat.
- `/premium` sells 30 days of Premium through Telegram Stars.
- Extra photos can be bought with Stars after included limits/credits are exhausted.
- `/voice` toggles voice answers.
- `/wake 08:00` creates a persistent wake-up reminder and stops repeated nudges when the user replies.
- `/timezone Europe/Moscow` sets local reminder time.
- `/testlevel 1..6` is owner-only and does not overwrite real relationship data.

## Local smoke test

```bash
python -m compileall .
python tests/smoke_test.py
```

Do not commit `.env`, local database files or API keys.
