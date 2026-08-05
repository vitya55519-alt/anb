# Railway deploy — AnnaBot V3.3 Hybrid

Required service variables:

```env
TELEGRAM_TOKEN=...
OPENAI_API_KEY=...
DATABASE_URL=${{Postgres.DATABASE_URL}}
IMAGE_MODEL=gpt-image-2
FAL_KEY=...
FAL_MODEL=fal-ai/bytedance/seedream/v4.5/edit
PHOTO_ROUTER_MODE=seedream
SEEDREAM_RELATIONSHIP_LEVEL=5
ADMIN_TELEGRAM_IDS=...
```

`FAL_KEY` must be created in the fal.ai dashboard and stored only in Railway Variables. Never commit it to GitHub.

Photo routing in production:

- `PHOTO_ROUTER_MODE=seedream` sends all Anna photo edits to fal.ai Seedream 4.5 Edit;
- OpenAI remains the chat model and can be selected explicitly for images only by setting `PHOTO_ROUTER_MODE=openai`;
- Seedream receives a neutral fully-clothed Anna identity anchor; clothing/location/hair/angle are edit instructions;
- a provider failure never sends a fake static result and never consumes quota or photo credit; the user gets Retry / Other scene buttons.

Seedream safety checking stays enabled.

After deploy, verify logs contain `AnnaBot started` and `Start polling`, then test `/testlevel 1..6` as the owner.


## Required Railway variables for V3.7
```text
TELEGRAM_TOKEN=...
OPENAI_API_KEY=...
FAL_KEY=...
FAL_MODEL=fal-ai/bytedance/seedream/v4.5/edit
PHOTO_ROUTER_MODE=hybrid
PHOTO_SET_SIZE=3
DATABASE_URL=${{Postgres.DATABASE_URL}}
IMAGE_MODEL=gpt-image-2
```

Important: older deployments may still have `PHOTO_ROUTER_MODE=seedream`. Change it to `hybrid`, otherwise all photos will continue to use Seedream.
