# Anna Bot — GitHub → Railway

## GitHub
Upload the contents of this folder to the repository root. Do not upload `.env` or API keys.

## Railway Variables
Set:
- `TELEGRAM_TOKEN`
- `AI_KEY` — your OpenAI API key
- `DATABASE_URL` — Railway PostgreSQL connection string
- `AI_MODEL` (optional)
- `IMAGE_API_KEY` (optional; defaults to `AI_KEY`)
- `IMAGE_MODEL` (optional)
- `TTS_API_KEY` (optional; defaults to `AI_KEY`)
- `TTS_MODEL` (optional)
- `TTS_VOICE` (optional)

## Deploy
Railway uses `railway.toml` and starts the service with:
`python main.py`

Create a PostgreSQL service in the same Railway project and attach its `DATABASE_URL`.

## Important
The current photo service uses a text-to-image fallback. The reference images are packaged under `data/references/anna/`, but exact identity consistency requires an image provider/model that supports reference-image conditioning/editing. Do not commit API keys.

### Railway dependency fix
`requirements.txt` includes APScheduler and SQLAlchemy-Utils, and the legacy Flask keep-alive import is intentionally not loaded by `helpers/__init__.py`. Railway runs the bot with long polling, so Flask is not required for the bot process.
