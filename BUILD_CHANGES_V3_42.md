# AnnaBot V3.42.0 — Support Replies, Lean Welcome, Partner Program 30% & Tariff Card

## The owner can finally answer support tickets
- Before this version tickets («🛟 Support user: …» / «💳 Payment support user: …») were **write-only**: the owner saw them but had no way to reply («люди уже пишут, я не могу ему ответить»).
- Now the owner answers by **replying to the ticket message** in his own chat. The catch-all `text_message` handler detects an admin reply to a ticket, parses `user: <id>` from the ticket header and `_deliver_admin_reply` sends the text to that user with a «💬 ответ поддержки:» («💬 support reply:») prefix, then confirms «↩️ отправлено пользователю <id> ✔».
- If the user blocks the bot, the owner gets an explicit «не удалось доставить ответ» instead of silence.

## Welcome-back: a short button list instead of a character wall
- The returning-user welcome no longer renders the nine-button character grid (character selection lives in the Mini App). `_welcome_back_rows` builds: **📱 Открыть приложение** (web_app, only when `PUBLIC_BASE_URL` is set) → **💰 Партнёрская программа** (full-width) → **📄 Условия + 🔐 Privacy**.
- Captions simplified: «с возвращением, {name} 🙂 девушки, чаты, картинки и магазин — в приложении 👇» (EN mirror).

## «Партнёрка» → «Партнёрская программа», big button, 40% → 30%
- `KB_LABELS['partner']` renamed to **💰 Партнёрская программа / 💰 Partner program**; the pre-v3.42.0 «💰 Партнёрка» label still resolves in `partner_button` so cached reply keyboards keep working.
- `MAIN_KB_ROWS`: partner is now its **own full-width row** (`app / credits / paint / partner / support+legal`) — a big button in both the main menu and the welcome screen.
- `REFERRAL_COMMISSION_PCT` default cut **40 → 30** (still env-tunable); the `/partner` command description now reads «💰 Партнёрская программа — 30% с покупок друзей». Percent strings elsewhere render from config, so they follow automatically.

## Premium pitch: Come Closer-style tariff card
- `premium_pitch_text` now embeds `_premium_tariff_lines` — the tariff card benchmarked from the competitor screenshot: a radio list with **○ 1 неделя** (Stars + fiat) and **● 1 месяц** (Stars + fiat + `−N%` savings badge), each with its price line; the monthly plan shows its **per-week price** and the struck «вместо 4×неделя» total.
- Prices switch to ₽ automatically when FreeKassa is enabled (`FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB` / `FREEKASSA_PREMIUM_PRICE_RUB`), otherwise Stars.
- The pitch keeps the discount countdown, the level-6 plateau hook and closes with «Разовый платёж, без автопродления.»

## Blue «Открыть приложение» menu button — verified, untouched
- The v3.33.0 `set_chat_menu_button(MenuButtonWebApp(...))` install (plus the v3.33.1 read-back verification log) is intact; photo 1 of the benchmark matches what we already ship.

## Ops
- Tests: `tests/test_v3420_support_reply_partner_premium_static.py` (support reply routing, welcome rows/captions, partner rename + full-width row + 30% + legacy label, tariff card + pitch embed, menu button); all 31 version pins bumped to 3.42.0.
