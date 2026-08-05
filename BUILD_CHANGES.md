# AnnaBot V3.3 Hybrid — changes

## Added

- fal.ai Seedream 4.5 Edit integration (`fal-ai/bytedance/seedream/v4.5/edit`).
- Hybrid provider router: GPT Image 2 for normal photos, Seedream for level 5–6 private non-explicit fashion requests.
- `FAL_KEY`, `FAL_MODEL`, `FAL_IMAGE_SIZE`, timeout, estimated cost and routing configuration.
- Seedream calls run off the asyncio event loop and have a hard timeout.
- fal safety checker remains enabled.
- One-time 18+ confirmation for adult-style fashion categories.
- Custom Stars flow: color -> optional stockings -> hairstyle -> location -> paid offer.
- Provider and estimated image cost telemetry in `photo_deliveries`.
- Relationship-gated photo access applies to free and paid requests; Stars cannot buy a higher relationship stage.
- Owner/admin photo testing without paying for every test frame.

## Conversation improvements

- Stronger anti-assistant persona rules.
- Six distinct relationship communication styles.
- Direct meta identity questions are answered honestly but briefly.
- Technical/coding requests are answered directly without turning into a flirting menu.
- One regeneration pass when a draft contains assistant-like phrases, excessive questions or unnecessary AI self-description.
- Short multi-paragraph replies can be sent as natural Telegram bubbles.

## Reliability

- Image moderation/technical failures do not consume quota or photo credits.
- Failed generations do not overwrite visual state.
- Higher-level sensitive-style requests do not loop through multiple providers.
- PostgreSQL migration adds `users.adult_confirmed`, `photo_deliveries.provider`, and `photo_deliveries.estimated_cost_usd`.
