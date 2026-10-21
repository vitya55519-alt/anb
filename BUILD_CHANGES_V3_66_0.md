# V3.66.0 — shop cards and missions that pay peaches

Owner (2026-10-21): «карточки криво сделаны, описание капец» and «миссии — для чего они?».

## Shop
- One Premium card: four short perks and two plan buttons (Месяц «выгоднее» / Неделя) with price and «+N 🍑 в подарок».
- Peach packs: three equal tiles with only the amount, the bonus (+500 🎁), «≈ N фото» and the price as the button; the middle pack wears «хит».
- Custom amount is one full-width row (input never clipped, button reads «Купить» until a number is typed).
- «🎁 Бесплатные персики каждый день — в «Миссиях»» row, promo code on one line, the price list folded into «Что сколько стоит».
- Long product descriptions stay for the quick-buy sheet; tiles use the new short `tagline`.

## Missions
- Every mission pays peaches (MISSION_PEACHES, 100–2000 🍑, 10 100 🍑 in total), claimed with a pulsing «Забрать +N 🍑» button (POST /webapp/api/missions/claim, idempotent via grant_photo_credits marker `mission_<key>`).
- The daily gift moved to the top of «Миссии»; summary «Забрано X из Y 🍑» + streak; finished-but-unclaimed missions first; done ones folded.
- Progress bars for 100 messages and 10 dates as well as the streaks.
- Red dot on the «Миссии» tab while peaches wait there.
- Fix: the app chat never ran the streak / first-message hooks, so app users' streaks and «Первые шаги» never moved. Each app chat turn now calls note_app_chat_message (streak, first message, 100 messages, voice) and the reply carries `missions_done` for a toast.
- Bot unlock text now says the peaches wait in «Миссии».
