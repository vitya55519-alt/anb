# AnnaBot V3.14.1 — Photo Pipeline Hardening

## Ordinary photo safety separation
- Ordinary `selfie/home/cafe/gym/...` prompts now use a dedicated neutral identity lock.
- Sensual/flirty Character DNA remains a dialogue concern and is not injected into ordinary photo prompts.
- Canonical face/body references remain active, but ordinary-provider prompt wording avoids unnecessary anatomy emphasis.
- `personal/lingerie/private_fashion` still route to Seedream.

## Nano Banana observability
Railway logs now show a deterministic path for every generated photo request:
- `PHOTO ROUTE selected ... provider=gemini_image`
- `Nano Banana frame success ...`
- or `PHOTO ROUTE FALLBACK ... from=gemini_image to=openai reason=...`
- `no_image` responses log top-level response keys, step types, and interaction id without logging secret keys or image bytes.

## Full-set library top-up
For ordinary `free` and `story` photo requests:
- if AI produces only 1/3 or 2/3, the missing frames are filled from accessible curated library photos;
- private scenes are never cross-filled from the ordinary library;
- only actually delivered library item ids are marked seen when a partial pack is used;
- a paid photo credit is still consumed only when the AI set itself is complete.

This preserves the product promise that an ordinary user photo request should finish with a complete visible set whenever eligible library content exists.
