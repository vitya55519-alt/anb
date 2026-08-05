# Railway check — V3.8

Pre-package checks:
- Python compileall: OK
- Static smoke: `STATIC_SMOKE_OK`
- Static photo routing: `PHOTO_ROUTING_STATIC_OK`
- SQLAlchemy test migration: communication profile table + recent photo state columns created
- Pure photo parser/season/wardrobe logic: tested with lightweight SDK stubs
- Pure language detection: tested for RU/EN/ZH/ES/FR/JA/KO
- Adaptive profile DB update: tested
- Adaptive LLM-profile merge: tested with a fake completion response
- Railway start command: `python main.py`
- PostgreSQL driver present in requirements
- No provider safety check disabled

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

## Note about local full pytest

The packaging container does not include the project runtime versions of `aiogram` / OpenAI SDK, so full import-based pytest cannot be executed here. Static parsing/compile, DB migrations and isolated pure logic were tested. Railway installs the declared `requirements.txt` before boot.
