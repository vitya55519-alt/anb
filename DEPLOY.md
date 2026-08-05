# Railway deploy — AnnaBot V3.3 Hybrid

Required service variables:

```env
TELEGRAM_TOKEN=...
OPENAI_API_KEY=...
DATABASE_URL=${{Postgres.DATABASE_URL}}
IMAGE_MODEL=gpt-image-2
FAL_KEY=...
FAL_MODEL=fal-ai/bytedance/seedream/v4.5/edit
PHOTO_ROUTER_MODE=hybrid
SEEDREAM_RELATIONSHIP_LEVEL=5
ADMIN_TELEGRAM_IDS=...
```

`FAL_KEY` must be created in the fal.ai dashboard and stored only in Railway Variables. Never commit it to GitHub.

Photo routing in hybrid mode:

- ordinary scenes and relationship levels 1–4 -> OpenAI `gpt-image-2` edit;
- non-explicit private/lingerie-fashion requests on levels 5–6 -> fal.ai Seedream 4.5 Edit;
- a technical/safety failure never consumes a photo credit and falls back to a local approved Anna reference rather than another identity.

Seedream safety checking stays enabled.

After deploy, verify logs contain `AnnaBot started` and `Start polling`, then test `/testlevel 1..6` as the owner.
