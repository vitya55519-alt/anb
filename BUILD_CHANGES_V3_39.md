# AnnaBot V3.39.0 — Come Closer Welcome + Character Page + In-App Media

## /start like Come Closer (owner screenshot benchmark)
- The welcome now leads with a **group photo banner** (`data/media/welcome_banner.png`) sent as a photo with a short punchy caption: «Что умеет этот бот? … ⬇️ Поехали! ⬇️» instead of the old ten-line feature list. Text fallback when the asset is missing.
- Returning users get the same banner with a one-line caption; the referral block moved out of the caption into its own short message so the photo message stays compact.
- A CTA row (📱 app `web_app` button + 💰 Партнёрка via the new `partner:open` callback) sits above the character picker on the welcome photo.
- The character picker is **two buttons per row** without the «· выбрать / · доступна» suffixes — the old eight-row wall is gone (`_character_pick_buttons` + `_pair_rows`, shared by onboarding and `/characters`).

## Peaches instead of strawberries
- The copied 🍓 «клубнички» branding is replaced with our own 🍑 «персики» everywhere user-facing: reply keyboard label, credits button, picture studio prices/toasts, profile stats, anime style icon.

## Character page (Come Closer layout)
- Tapping a storefront card opens a full page: horizontal **photo strip** (face + look via `/webapp/photo/{id}?i=N`), name + age/status, a big «💬 Начать чат» CTA, the bio block and the italic **СЮЖЕТ** block (scenario hook), plus «❤️ Сделать твоей».
- «Начать чат» opens the shared in-app dialog; the chats list still opens dialogs directly.

## In-app chat media — everything the bot dialog has
- New action buttons in the chat input: 📸 photo / 🎥 circle / 🎙 voice → `POST /webapp/api/chat/media`.
  - photo: identity-locked render through the canonical face reference, costs 1 🍑 charged **after** success;
  - circle: Premium-only, uses the premium daily free slot, generated through the bot's own engine chain (Gemini → Replicate → fal → HF) with `CIRCLE_PROMPT`;
  - voice: synthesizes her last reply (or the scenario hook) with her TTS voice.
- Media files live per-user in `data/app_media/<telegram_id>/` with unguessable names, served owner-scoped via `GET /webapp/media/{filename}`; history rows carry `media_kind`/`media_url` (new nullable `messages` columns, auto-migrated) so reloads render them again: round looping video for circles, audio player for voice, image for photos.

## Heroines: glamorous + curvy
- All five v3.38 heroines re-shot: glamorous beauty faces (v3) and curvy hourglass full-bust looks (v4), fully clothed and tasteful; `preserve_identity` anchors now carry the «curvy hourglass figure with a full bust» line so future generations keep the figure.

## «Персонажи» segment switch (Come Closer style)
- The tab now has two segments: **🍑 Персиковый сад** (our official roster) and **👥 Сообщество** (girls people created in the constructor). The switch re-renders the cached grid without refetching; the «＋ Создать» card lives only in the community segment.

## Studio reliability
- Freeform renders (`Картинки` tab, in-app chat photos) try **Seedream t2i** before Gemini, so one provider outage/refusal no longer ends in «Не получилось нарисовать»; admins now see the failure reason right in the studio toast.

## Ops
- New endpoints: `POST /webapp/api/chat/media`, `GET /webapp/media/{filename}`; `/webapp/photo/{id}` gained `?i=`.
- Tests: `tests/test_v3390_welcome_static.py` (welcome banner, compact picker, peaches, character page, media gates/persistence, segment switch, studio engines); version pins bumped to 3.39.0.
