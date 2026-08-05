# V3.7.1 OpenAI normal-photo moderation fix

- Ordinary GPT Image 2 scenes use a neutral fully-clothed identity anchor: `00_openai_safe_fullbody.png`.
- GPT prompts avoid anatomy-emphasis wording and use general-audience wardrobe language.
- GPT normal-photo prompt explicitly requests ordinary lifestyle photography.
- Seedream keeps the stronger identity/body lock for higher-level non-explicit glamour/lingerie fashion.
- Railway logs show `OpenAI normal-photo set request ... safe_prompt=true` before generation.

# V3.6 — Seedream input-validation fix

- Added `00_seedream_face_safe.png`, a neutral face-only identity anchor.
- Seedream now uses the neutral anchor instead of the white-top source that fal partner validation rejected with HTTP 422.
- Kept `enable_safety_checker=True`; this is a compliance fix, not a safety bypass.
- Simplified the Seedream prompt for ordinary photo generation and added reference-name logging.
- Failed generations still do not consume free quota or photo credits.

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

## V3.4 — photo progression + Seedream transport fix

- Added persistent Telegram main menu: Chat / Photos / Looks / Premium / Profile / Settings.
- Photo menu now shows the next locked photo category with a lock and required relationship level.
- Added level-4 `personal` photo category and level-5 private fashion preview.
- Locked categories cannot be bought with Stars; tapping them explains the required relationship level.
- Seedream 4.5 is now the default photo provider in production. OpenAI remains the chat provider and optional explicit image mode.
- Replaced the `fal-client` wrapper path with a direct authenticated `fal.run` HTTP request using the documented Seedream 4.5 schema.
- Generation uses neutral fully-clothed Anna anchors only, reducing moderation noise.
- Removed fake/static image fallback. A provider failure now returns Retry / Other scene buttons and consumes no free quota or paid credit.
- Added clearer provider error logging for Railway diagnosis.


## V3.5 — relationship-based daily photo quota
- Relationship levels 1–2: 1 free generated photo per UTC day.
- Relationship levels 3–6: 2 free generated photos per UTC day.
- After the free quota, a standard photo costs `PHOTO_COST_STARS` (25 Stars by default) or consumes an already purchased photo credit.
- Failed generations do not consume the daily free allowance or a photo credit.
- Premium no longer overrides the relationship-based free quota; its monthly photo credits remain prepaid extra generations.


## V3.7
- New Anna identity anchors.
- Hybrid routing restored: ordinary -> GPT Image 2, bold non-explicit lingerie/boudoir -> Seedream.
- Reworked structured prompts with identity lock, scene, outfit, hair, shot, lighting, quality, negative blocks.
- Outfit and hairstyle pools avoid immediate repetition.
- Each request can deliver up to 3 photos while consuming one free request/credit.


## V3.7.2 routing correction
- `selfie`, `home`, `park`, `cafe`, `outfit`, `mirror`, `evening`, and mainstream `fashion` stay on GPT Image 2 in hybrid mode.
- `personal` (relationship level 4) and `lingerie` (level 5+) route to Seedream 4.5.
- This avoids repeated OpenAI `moderation_blocked [sexual]` failures for the more private `personal` scene while preserving GPT Image 2 for ordinary photos.
- Seedream safety checking remains enabled. Failed generation does not consume the free daily request or paid credit.


## V3.7.3 — Seedream timeout/retry reliability

- Seedream set generation now requests one image per provider call instead of 3 images in one long request.
- Read timeout increased to 210s by default, with separate connect/write/pool timeouts.
- Added bounded retry for transport timeouts and transient 408/429/5xx responses.
- Provider policy/validation 4xx responses are not retried. Safety checker remains enabled.
- If at least one image in a 3-photo Seedream set succeeds and a later image fails, the successful partial set is delivered and the request counts once.
- Added elapsed-time and retry diagnostics to Railway logs.
