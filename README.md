# AnnaBot V3.3 Hybrid

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
