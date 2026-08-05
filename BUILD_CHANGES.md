# V3.8 build changes

## Adaptive communication

Added `CommunicationProfile` PostgreSQL model and `services/adaptation_service.py`.

Per-user profile stores only bounded communication-style metadata:
- preferred language and confidence;
- rolling message-length/emoji/question/uppercase/slang signals;
- structured style JSON;
- recurring expression/slang JSON;
- bounded local token counters;
- analysis cadence.

`chat_service.reply()` now:
1. observes the user's current message locally;
2. builds a per-user adaptation context before the response;
3. preserves Anna's base personality as the dominant voice;
4. periodically refines slang/style through the configured chat model;
5. keeps adaptation failures non-fatal.

`/reset` clears the learned communication profile together with normal memory/history.

Added bounded visual-preference learning (`visual_json`) for frequently selected scenes, colors and hairstyles. Photo generation can reuse strong preferences probabilistically while preserving diversity and anti-repeat rules.

## Photo progression

Expanded scene catalogue: street, shop, car, restaurant, cinema, embankment, bar, karaoke, rooftop, club and premium private fashion.

Added:
- scene groups;
- relationship-level wardrobe pools;
- season rules;
- 3-frame progression pack rules (`BASE -> STYLISH -> PREMIUM`);
- explicit relationship visual progression in image prompts;
- context-aware outfit selection;
- anti-repeat recent outfit/hairstyle state;
- natural self-shot requirement (front camera / mirror / phone self-timer);
- photo-intent routing before normal chat reply.

Hybrid routing remains:
- ordinary scenes -> GPT Image 2;
- personal/private/lingerie -> Seedream 4.5.

Seedream one-image-per-request timeout/retry reliability from V3.7.3 is preserved.

## Database

Automatic SQLAlchemy/PostgreSQL migration behavior:
- new table: `communication_profiles`;
- new `character_states` columns: `recent_outfits_json`, `recent_hairstyles_json`.

No manual SQL migration is required for the existing Railway database.
