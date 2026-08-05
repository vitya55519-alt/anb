# AnnaBot V3.8 — Adaptive Persona + Visual Progression

Railway-ready Telegram AI companion with persistent memory, six relationship levels, adaptive conversation style, proactive messaging, Telegram Stars, PostgreSQL and a hybrid photo engine.

## V3.8: Anna adapts to each user

Anna does **not** rewrite her own code or system prompt. Instead, every user gets a bounded `CommunicationProfile` stored in PostgreSQL.

The profile learns gradually:
- preferred/current language;
- usual message length;
- formality;
- humor and sarcasm level;
- emoji/question habits;
- recurring slang and conversational expressions;
- confidence for learned expressions.

Cheap local signals are updated on every message. Every `ADAPTATION_ANALYZE_EVERY` messages (default 5), the chat model refines the style/slang profile. Anna may occasionally use one familiar expression when it naturally fits, but her base personality always remains stronger than mirroring.

Sensitive categories are explicitly excluded from style extraction. `/reset` deletes messages, memories, relationship progress **and** the learned communication profile.

Anna also learns lightweight **photo preferences** from actual choices: favorite scenes, repeatedly requested colors and hairstyles. These are used softly (roughly half personalization / half diversity and surprise), so the photo feed does not collapse into the same look every time.

Language detection supports Russian, English, Chinese, Spanish, German, French, Italian, Portuguese, Ukrainian, Japanese and Korean, while the main chat prompt can still answer in other languages by following the user's latest message.

## V3.8: photo progression pack

One photo request returns up to 3 images as a progression pack:
1. **Base** — natural believable frame;
2. **Stylish** — more polished styling/pose;
3. **Premium** — strongest composition and outfit allowed at the current relationship level.

The relationship level now materially affects wardrobe and styling:
- level 1: friendly fitted casual;
- level 2: more feminine/waist-defined;
- level 3: clearly more stylish and confident;
- level 4: polished personal fashion;
- level 5: glamorous personalized styling;
- level 6: premium exclusive styling, still non-explicit.

### Context-aware wardrobe

Wardrobe is selected from scene + season + relationship level. A visible summer park/street scene will not receive a winter sweater/hoodie unless explicitly requested. Summer pools include fitted tops, shorts, skirts, sundresses, tailored trousers and fitted summer dresses. Higher levels progressively add stronger figure-flattering dresses and premium fitted looks without changing Anna's underlying body proportions.

Recent outfits (last 6) and hairstyles (last 4) are stored in `CharacterState` to reduce repetition.

### Photo locations / unlocks

Level 1:
- Selfie, Home, Park, Cafe, Street

Level 2:
- Mirror, Outfit, Shop, Car

Level 3:
- Restaurant, Cinema, Embankment, Fashion

Level 4:
- Evening, Bar, Karaoke, Rooftop

Level 5:
- Club, Personal, Private fashion/lingerie category

Level 6:
- Premium private fashion

Locked categories remain visible in the menu as progression hints.

## Hybrid photo routing

- Ordinary fully clothed lifestyle/fashion scenes -> `gpt-image-2`.
- `personal`, `lingerie`, and `private_fashion` -> Seedream 4.5.
- Seedream safety checking remains enabled.
- Seedream generates one image per provider call with timeout/retry, but up to 3 images are delivered as one user-visible set.
- Failed generation does not consume free quota or photo credit.

Natural photo commands are intercepted **before** normal chat generation. For example, a natural request to photograph herself from behind is normalized into a fully clothed, non-explicit personal fashion composition rather than producing a text refusal first.

## Daily photo allowance

- Relationship levels 1–2: 1 free photo request/day (up to 3 images).
- Relationship levels 3–6: 2 free photo requests/day (up to 3 images each).
- Extra standard request: `PHOTO_COST_STARS` (default 25⭐).
- Custom photo: `CUSTOM_PHOTO_COST_STARS` (default 40⭐).

## Required Railway variables

```text
TELEGRAM_TOKEN=...
OPENAI_API_KEY=...
FAL_KEY=...
DATABASE_URL=${{Postgres.DATABASE_URL}}
IMAGE_MODEL=gpt-image-2
FAL_MODEL=fal-ai/bytedance/seedream/v4.5/edit
PHOTO_ROUTER_MODE=hybrid
PHOTO_SET_SIZE=3
```

Adaptive communication defaults require no new secret:

```text
ADAPTATION_ENABLED=true
ADAPTATION_ANALYZE_EVERY=5
ADAPTATION_MAX_EXPRESSIONS=12
```

See `DEPLOY.md` and `RAILWAY_CHECK.md`.

## V3.9 Commercial Core

V3.9 adds a commercial-beta reliability layer: onboarding, background photo jobs, immediate per-frame delivery, OpenAI safe retry/partial-pack preservation, product analytics, `/stats`, optional image budget guards, and a lightweight Anna life/pending-topic state for better proactive continuity. See `BUILD_CHANGES.md` and `V3_9_CHECKLIST.md`.
