## V3.13.0
Onboarding + Quest UX + Nano Banana reliability. `/start` now presents a real character picker, Anna sends a photo+description followed by a capabilities message, `🎭 Образы` is removed from the main keyboard, and `✨ Возможности` is available at any time. Quests span L1-L6 and announce themselves when a relationship level unlocks them. Nano Banana ordinary-photo generation uses the Gemini REST Interactions endpoint with explicit API-key validation and GPT Image 2 fallback.

## V3.12.1
Gemini dialogue + Nano Banana 2 ordinary-photo routing + a more sensual/flirty Anna personality. Seedream remains the private/lingerie photo provider; GPT Image 2 remains fallback.

# AnnaBot V3.12.0 — Gemini Dialogue + Veo Video Foundation


## V3.12 highlights

- Gemini visible-chat provider with automatic OpenAI fallback.
- Default `gemini-3.5-flash` works with the current AI Studio Free tier; switch to `gemini-3.6-flash` after billing if desired.
- Character DNA, memory, relationship and anti-repeat prompts are preserved across providers.
- Optional Veo 3.1 Lite image-to-video backend for `🎬 Оживить последнее фото`.
- Video is OFF by default until Google paid billing is enabled.
- Paid video jobs run in background and automatically attempt a Telegram Stars refund if generation fails.
- `/geministatus` lets the owner inspect the active chat/video routing without revealing the API key.

## V3.11 highlights

- Market-readiness layer: Terms, Privacy, Support, 18+ consent and full data deletion.
- Character DNA + Competency Gate: Anna does not fake expertise (e.g. Python) outside her defined skills.
- Per-photo cumulative collection with `/collection` and `🖼 Коллекция`.
- 10-photo-per-level importer: 10 photos are saved as 3+3+3+1, nothing is silently discarded.
- Quest Core with canonical choice, persistent story memory and paid/Premium alternative routes.
- Telegram Stars pre-checkout validation and owner Star refund command.
- V3.10.7 canonical Anna identity and GPT Image 2 / Seedream hybrid photo routing are preserved.

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


## V3.9.1 Relationship + Telegram Photo Library

- Six natural relationship stages: Знакомство → Симпатия → Доверие → Близость → Особая связь → Наша история.
- Hidden dimensions add familiarity, continuity and connection; relationship milestones are persisted and can appear in the profile/chat context. Earned relationship level is not reduced by absence.
- Free ordinary photos use the curated Telegram `file_id` library first. If no matching pack exists, the normal AI generator is used. Custom/credit/admin photo generation remains AI-based.
- Owner import flow: `/libraryimport` → character → scene → level → progression/collection → upload up to 30 Telegram photos → preview/save. No manual renaming is required.
- `/library` shows coverage by character / scene / relationship level.
- `👩 Персонажи` contains an Emily fake-door; the public second character remains disabled until an original stable identity is finalized.
- `/today` or `/plans` lets the user influence a small fictional life-state choice; vague requests like “покажись” can then use the current story location.
- `PHOTO_LIBRARY_SEEDREAM5_PROMPTS.md` contains the offline prompt pack for producing curated library content.
- OpenAI `elapsed` crash is fixed; Seedream 422 receives one safety-preserving neutral retry before partial delivery.


## V3.9.2 fast library import
`/libraryimport` now always groups uploads into automatic 3-photo packs after character → scene → relationship level. Upload 30 photos in order and save once: 1–3 become pack 1, 4–6 pack 2, …, 28–30 pack 10. Existing V3.9.1 one-photo packs can be regrouped without re-upload using `/libraryregroup anna_01 selfie 1`.


## V3.10.0 Telegram Character Cards Admin
The `👩 Персонажи` screen is now backed by persistent character-card rows in the database. Owners configured in `ADMIN_TELEGRAM_IDS` can open `/admin` (or the admin-only `🛠 Админка` reply-keyboard button after `/start`) and edit Anna/Emily public cards directly in Telegram: name, age, description, status, visibility and cover photo. Card edits do not modify AI personality/memory/photo identity. See `BUILD_CHANGES_V3_10_0.md`.


## V3.10.4 visual identity engine v2

- GPT Image 2 ordinary-scene generation now uses two ordered reference anchors: a canonical face anchor and a canonical body-proportion anchor.
- Anna's face and body identity are separate prompt blocks; clothing, scene and safety styling may not redesign her established physique.
- Drift-prone scenes (`mirror`, `gym`, `cafe`, `restaurant`, `home`, `outfit`, `selfie`) receive an extra body-consistency reinforcement.
- Safe retry uses a safer fully clothed body anchor while preserving the same identity rules.
- GPT Image 2 remains the ordinary fully clothed provider; Seedream 4.5 routing remains unchanged for personal/private-fashion scenes.
- ZIP is flat for GitHub/Railway deployment: `main.py` and `requirements.txt` are at archive root.

See `BUILD_CHANGES_V3_10_4.md`.

## V3.10.3 deployment candidate

- Keeps the existing Telegram Stars checkout unchanged.
- Keeps the V3.10.2 payment admin and future-feature locks.
- QR payment records remain owner-admin managed: create multiple QR entries, upload/replace the QR image in Telegram, edit its label/instructions/status, preview, or delete it without changing code or redeploying.
- QR images are stored by Telegram `file_id`; metadata is stored in PostgreSQL.
- No LAVA checkout integration is enabled in this build.
- This release is packaged as the GitHub/Railway test candidate.

## V3.10.2 Payment Admin + future feature locks

- Telegram admin now has `💳 Способы оплаты`.
- `Telegram Stars` is a protected system method for digital purchases inside Telegram.
- Owners can add arbitrary **QR** entries or **HTTPS provider links**, rename them, edit instructions, change external status, preview them, replace QR images, and delete non-system methods without redeploy.
- QR images are stored as Telegram `file_id`; payment-method metadata is stored in PostgreSQL.
- External QR/link methods are deliberately **not** wired into Premium/photo/quest checkout because Telegram requires Stars for digital goods and services inside Telegram.
- `/paysupport <описание>` forwards payment-support requests to configured owners.
- Character cards and Premium screen now expose locked `🎬 Оживить фото · скоро` and `📞 Звонок с Анной · скоро` affordances; they do not activate unfinished functionality.

See `BUILD_CHANGES_V3_10_2.md`.

## V3.12 Gemini dialogue + video

V3.12 can use Gemini as the primary user-visible dialogue engine while keeping OpenAI as an automatic fallback. Configure Railway with `GEMINI_API_KEY`; the default model is `gemini-3.6-flash`. The existing OpenAI image pipeline, Seedream private-photo route, memory extraction and TTS remain independent.

V3.19.4 removed Gemini/Veo video. Image-to-video runs on Replicate (default model `minimax/hailuo-2.3-fast`) with fal.ai and HF-space fallbacks; the Stars-paid `Оживить последнее фото` flow unlocks when `REPLICATE_API_TOKEN` is set, with automatic Stars refund attempts when generation fails.


## V3.14 Linked photo videos

Owner-uploaded library photos can now carry an optional ready-made Telegram video. During `/libraryimport`, send `photo → video → next photo`; users see `🎬 Смотреть видео` under paired photos. The video is served from Telegram `file_id`, inherits the photo relationship gate, and does not invoke Veo or consume generation quota. See `BUILD_CHANGES_V3_14.md`.

## V3.14.1 Photo Pipeline Hardening
Ordinary photo generation now keeps sensual chat DNA out of image prompts, logs the Nano Banana → OpenAI route explicitly, and fills partial ordinary free/story AI sets from the ready library up to the configured set size when accessible content exists. Private/lingerie routing remains on Seedream. See `BUILD_CHANGES_V3_14_1.md`.
