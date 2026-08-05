# AnnaBot V3.4 V3.3 Hybrid

Telegram AI-companion MVP with one persistent Anna identity, long-term memory, six relationship stages, reminders, proactive messaging, Telegram Stars, voice, PostgreSQL, and a hybrid reference-based photo engine.

## Photo engine

- `gpt-image-2` handles ordinary edits: outfit, hairstyle, place, selfie, mirror, park, cafe and angle changes.
- `fal-ai/bytedance/seedream/v4.5/edit` handles higher-level non-explicit private fashion edits from relationship level 5 onward.
- The same Anna reference pack is used to preserve face and body proportions.
- Adult-style fashion categories require a one-time 18+ confirmation.
- Stars buy customization, not relationship progression.
- Custom paid flow supports color, stockings, hairstyle and location.
- Safety/technical failures do not consume paid credits or corrupt visual state.

## Conversation

Anna is intentionally not written as an assistant. Replies vary in length and intent, do not end every turn with a question, can include opinions/disagreement/callbacks, and use a one-pass quality rewrite when the draft sounds assistant-like. Direct questions about whether Anna is real are answered honestly and briefly.

## Railway variables

See `DEPLOY.md` and `.env.example`.


## V3.4 photo UX

Seedream 4.5 is the default image editor. The photo menu previews the next locked relationship-level photo category. Failed generation is reported honestly and never replaced with a repeated static image; free quota and paid credits are only consumed after successful delivery.


### Daily photo allowance
- Relationship levels 1–2: 1 free generated photo per day.
- Relationship levels 3–6: 2 free generated photos per day.
- Extra standard photos use prepaid photo credits or a Telegram Stars invoice (`PHOTO_COST_STARS`, default 25⭐).
