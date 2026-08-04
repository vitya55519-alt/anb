# Railway deployment

1. Create/attach a PostgreSQL service in Railway.
2. Make sure the bot service receives `DATABASE_URL` from that database.
3. Add `TELEGRAM_TOKEN` and `OPENAI_API_KEY` to Railway Variables.
4. Optionally add `ADMIN_TELEGRAM_IDS` with your numeric Telegram ID.
5. Deploy from GitHub. Railway runs `python main.py` from `railway.toml`.

The application normalizes Railway `postgres://` / `postgresql://` URLs to SQLAlchemy psycopg URLs. Local development uses SQLite when `DATABASE_URL` is absent.
