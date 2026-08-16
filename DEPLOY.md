# Railway deployment — AnnaBot V3.8

## Required variables on Railway `web`

```text
TELEGRAM_TOKEN=...
OPENAI_API_KEY=...
FAL_KEY=...
DATABASE_URL=${{Postgres.DATABASE_URL}}
IMAGE_MODEL=gpt-image-2
FAL_MODEL=fal-ai/bytedance/seedream/v4.5/edit
PHOTO_ROUTER_MODE=hybrid
PHOTO_SET_SIZE=3
ADMIN_TELEGRAM_IDS=...
```

Do **not** leave `PHOTO_ROUTER_MODE=seedream` from an older deployment, because that would force all ordinary photos through Seedream.

Optional/defaulted:

```text
FAL_IMAGE_SIZE=portrait_4_3
FAL_TIMEOUT_SECONDS=210
FAL_CONNECT_TIMEOUT_SECONDS=20
FAL_WRITE_TIMEOUT_SECONDS=60
FAL_POOL_TIMEOUT_SECONDS=30
FAL_RETRIES=2
FAL_RETRY_BACKOFF_SECONDS=2
ADAPTATION_ENABLED=true
ADAPTATION_ANALYZE_EVERY=5
ADAPTATION_MAX_EXPRESSIONS=12
FREE_PHOTOS_LEVEL_1_2=1
FREE_PHOTOS_LEVEL_3_6=2
PHOTO_COST_STARS=25
CUSTOM_PHOTO_COST_STARS=40
```

## Deploy behavior

`railway.toml` starts:

```text
python main.py
```

At startup `services.db.init_db()` creates the new `communication_profiles` table and adds missing recent-outfit/recent-hairstyle columns automatically. Existing user data is preserved.

## First live checks

1. Look for `AnnaBot started` and `Start polling`.
2. Chat for several messages; after ~5 messages the communication profile can be refined automatically.
3. `/testlevel 1` -> Park/Home: verify context-appropriate casual fitted wardrobe.
4. `/testlevel 6` -> same scene: verify visibly more premium/styled wardrobe.
5. In August/summer Park: verify no heavy sweater/hoodie unless explicitly requested.
6. Check a standard scene routes to OpenAI.
7. Check a level-5 Personal/Private scene routes to Seedream and returns up to 3 images.

`FAL_KEY`, Telegram token and OpenAI key must remain Railway secrets and must never be committed.

## V3.9 optional guardrails

These are optional and default to disabled/zero:

```text
DAILY_IMAGE_BUDGET_USD=0
MONTHLY_IMAGE_BUDGET_USD=0
OPENAI_IMAGE_ESTIMATED_COST_USD=0
PHOTO_PROGRESS_MESSAGE_DELAY_SECONDS=18
```

Set the image cost estimate to your effective provider cost if you want meaningful internal cost totals. Keep a single Railway replica while Telegram uses long polling; multiple replicas can cause `Conflict: terminated by other getUpdates request`.


## V3.12 Gemini dialogue and optional Veo video

For the AI Studio key shown as Free tier, add these Railway Variables first:

```text
GEMINI_API_KEY=<your full key; never commit it>
CHAT_PROVIDER=gemini
GEMINI_CHAT_MODEL=gemini-3.5-flash
GEMINI_THINKING_LEVEL=minimal
CHAT_FALLBACK_OPENAI=true
GEMINI_VIDEO_ENABLED=false
```

After Google paid billing is enabled, you may switch chat to the newest Flash model and unlock video:

```text
GEMINI_CHAT_MODEL=gemini-3.6-flash
GEMINI_VIDEO_ENABLED=true
GEMINI_VIDEO_MODEL=veo-3.1-lite-generate-preview
GEMINI_VIDEO_DURATION_SECONDS=8
GEMINI_VIDEO_RESOLUTION=720p
GEMINI_VIDEO_ASPECT_RATIO=9:16
VIDEO_COST_STARS=100
```

Do not put the real Gemini API key into `.env.example`, GitHub, logs, screenshots, or support messages. Use Railway Variables.
