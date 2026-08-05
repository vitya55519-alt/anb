# AnnaBot V3.9.0 — Commercial Core

This release is focused on closed-beta commercial readiness rather than adding random features.

## Onboarding
- New `/start` value proposition explains memory, adaptive communication, relationship progression, photos and proactive follow-ups.
- Inline choices: `💬 Познакомиться` and `📸 Что ты умеешь?`.
- Product events capture onboarding entry and actions.

## Reliability UX for photo packs
- Photo generation runs in a background asyncio task so the user can keep chatting while a set is generated.
- Anna immediately sends a natural status message and a follow-up progress ping if generation is still running.
- Each successful frame is sent to Telegram as soon as it is ready; the user no longer waits for all 3 frames before seeing anything.
- One active photo job per user prevents accidental duplicate generations from repeated taps.
- Seedream remains one-provider-request-per-frame with bounded timeout/retry.

## OpenAI image moderation resilience
- Normal OpenAI prompts were made more clearly general-audience while retaining fashion progression.
- OpenAI relationship progression now escalates styling/accessories/composition rather than body emphasis.
- If a single frame is `moderation_blocked`, only that frame gets one stricter general-audience safe retry.
- If a later frame still fails, already successful frames are preserved and delivered as a partial set.
- No safety checker is disabled and no moderation bypass is attempted.

## Fairness for partial packs
- A paid photo credit is consumed only for a complete 3-frame pack.
- A 1-frame free partial does not consume the daily free request.
- A useful 2/3 free pack counts as one free request.
- Failed generations do not consume quota or credits.

## Product analytics
- New `product_events` table.
- Tracks onboarding, chat activity, photo requests, frame readiness, partial/failure events, paywall views, purchases, proactive sends and relationship level-ups.
- `/stats` and `/adminstats` for admin IDs show users, active users, new users, D1/D3/D7 retention, messages, photo request/failure/partial rate, first-frame latency, image cost and Stars.

## Cost controls
- Optional `DAILY_IMAGE_BUDGET_USD` and `MONTHLY_IMAGE_BUDGET_USD` budget guards.
- `OPENAI_IMAGE_ESTIMATED_COST_USD` can be set to the current effective cost per successful OpenAI image for internal cost telemetry.
- Seedream continues to use `FAL_ESTIMATED_COST_USD`.

## Anna life / retention continuity
- Lightweight fictional day-part state: activity, location, mood and energy.
- State changes at a bounded cadence so Anna does not invent a new situation every message.
- Future-plan language can create a `pending_hook`; the next proactive message can naturally return to that unfinished topic.
- A pending hook is consumed after one proactive follow-up so it does not repeat forever.
- Relationship stage changes are tracked and the next reply can subtly feel warmer/more familiar without announcing a system level.

## Photo context retained from V3.8
- Progression packs: Base -> Stylish -> Premium.
- Scene + season + relationship level + anti-repeat wardrobe + hairstyle + user visual preferences.
- Summer outdoor scenes filter sweaters/hoodies/coats.
- Expanded locations: street, shop, car, restaurant, cinema, embankment, bar, karaoke, rooftop and club.

## Railway notes
- No new required secrets.
- Keep `PHOTO_ROUTER_MODE=hybrid` and `PHOTO_SET_SIZE=3`.
- Budget variables default to `0` (disabled) until you choose limits.
- Telegram long polling should run with one Railway web replica to avoid `getUpdates` conflicts.
