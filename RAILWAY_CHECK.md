# Railway deployment check — V3.7

Static deployment checks completed before packaging:

- Python syntax / compileall: OK
- Static smoke test: OK (`STATIC_SMOKE_OK`)
- Photo routing static test: OK (`PHOTO_ROUTING_STATIC_OK`)
- `railway.toml` start command: `python main.py`
- `Procfile`: `worker: python main.py`
- PostgreSQL driver declared: `psycopg[binary]>=3.2.0`
- Telegram dependency declared: `aiogram==3.15.0`
- OpenAI SDK declared: `openai>=2.0.0`
- HTTP client for fal declared: `httpx>=0.27.0`
- No hard-coded OpenAI / fal / Telegram secrets found
- ZIP integrity checked after packaging

## Railway variables

Required on the `web` service:

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

Optional/defaulted:

```text
FAL_IMAGE_SIZE=portrait_4_3
FAL_TIMEOUT_SECONDS=150
FREE_PHOTOS_LEVEL_1_2=1
FREE_PHOTOS_LEVEL_3_6=2
PHOTO_COST_STARS=25
CUSTOM_PHOTO_COST_STARS=40
```

## Important for the current Railway service

Older V3.6 deployments used:

```text
PHOTO_ROUTER_MODE=seedream
```

For V3.7 this must be changed to:

```text
PHOTO_ROUTER_MODE=hybrid
```

Otherwise the environment variable intentionally overrides the new default and all images will still be routed to Seedream.

## What is and is not verified

The package has been statically verified for Railway layout and Python syntax. A real boot against Railway, Telegram, PostgreSQL, OpenAI and fal requires the real server-side secrets and cannot be executed inside the packaging environment. The first production test should therefore confirm one ordinary photo routes to OpenAI and one level-5 private-fashion photo routes to Seedream.
