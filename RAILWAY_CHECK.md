# Railway check — V3.9 Commercial Core

Pre-package checks performed in the build container:
- Python `compileall`: OK
- Static smoke: `STATIC_SMOKE_OK`
- V3.9 commercial static check: `V39_COMMERCIAL_STATIC_OK`
- Static photo routing: `PHOTO_ROUTING_STATIC_OK`
- Relationship engine tests: `3 passed`
- SQLite schema bootstrap: `DB_SCHEMA_OK`, including `product_events`
- AST parse of all Python files: OK
- Secret-pattern scan: no embedded provider/bot keys found
- Railway start command: `python main.py`
- PostgreSQL driver present in requirements
- Provider safety check remains enabled; V3.9 safe retry makes a blocked frame more general-audience rather than bypassing moderation

## Required Railway variables

```text
TELEGRAM_TOKEN=...
OPENAI_API_KEY=...
FAL_KEY=...
DATABASE_URL=${{Postgres.DATABASE_URL}}
IMAGE_MODEL=gpt-image-2
FAL_MODEL=fal-ai/bytedance/seedream/v4.5/edit
PHOTO_ROUTER_MODE=hybrid
PHOTO_SET_SIZE=3
```

## Optional commercial guardrails

```text
DAILY_IMAGE_BUDGET_USD=0
MONTHLY_IMAGE_BUDGET_USD=0
OPENAI_IMAGE_ESTIMATED_COST_USD=0
PHOTO_PROGRESS_MESSAGE_DELAY_SECONDS=18
```

`0` disables a money guard / cost estimate. Set the values in Railway after choosing your beta budget and the effective OpenAI image cost you want to use for internal telemetry.

## Runtime-test note

The packaging container does not include the project runtime versions of `aiogram` and the OpenAI SDK, so provider/API integration tests were not executed against live Telegram, OpenAI or fal.ai. Railway installs `requirements.txt` before boot. The project itself was syntax/compile checked, DB schema bootstrapped, and dependency-free static tests were run.

## Telegram polling

Use one Railway bot replica with `getUpdates` long polling. Multiple live replicas can cause `TelegramConflictError: terminated by other getUpdates request`.
