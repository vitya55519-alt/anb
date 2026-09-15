# AnnaBot V3.33.0 — Telegram Mini App (WebApp) Storefront

Owner request after benchmarking the payment partner's sample bot
(@come_closer_bot): «сможем ли мы создать приложение как у них?» — yes.
v3.33.0 is the skeleton; the roadmap is v3.34 shop payments, v3.35 photo
ordering, v3.36 soft currency/growth loop.

## What ships in v3.33.0
- **Page** `webapp/index.html` — single-file dark-theme Mini App loaded via
  the official `telegram-web-app.js` SDK (intentionally not SRI-pinned:
  Telegram serves it unversioned and updates it in place; inside the Telegram
  client the client's own copy takes precedence — see the comment in the HTML).
  Bottom navigation: **Персонажи / Магазин / Профиль / Документы**. RU/EN via
  the account `language_code`.
- **Backend** `services/webapp_service.py`:
  - `validate_init_data` — the official Telegram initData HMAC check
    (secret = HMAC-SHA256("WebAppData", bot_token); hash over the sorted
    data_check_string; 24h freshness window) — the `/api/me` endpoint
    authorizes users with it, returning 401 otherwise;
  - `api_me` (premium, selected girl, relationship level, streak),
    `api_characters` (visible cards + photo URLs), `api_shop` (structured
    prices from the same config constants the bot charges),
    `api_legal` (the v3.32.0 Platega documents + чекап word);
  - `character_photo` — canonical face PNGs for built-ins, cached constructor
    avatars for custom personas; no Telegram API calls, bytes straight from
    disk.
- **Routes** on the existing Railway aiohttp app: `GET /webapp` (page),
  `/webapp/api/me|characters|shop|legal`, `/webapp/photo/{character_id}`.
- **Entry point**: `set_chat_menu_button(MenuButtonWebApp)` at startup —
  gives the blue «Открыть приложение» button in the bot profile, exactly like
  the sample bot. Requires `PUBLIC_BASE_URL` (the same Railway domain
  FreeKassa already uses — already configured there); skipped silently
  otherwise. The call is guarded so a Telegram hiccup cannot kill startup.
- `/api/me` also `ensure_user`s the visitor and tracks `webapp_opened`.

## Not in this build (by design)
- Chat stays native in the bot — the Mini App does not replicate the dialog.
- Payments still happen in the bot (same prices); in-app invoices come later.
- The Telegram SDK script is loaded from telegram.org (platform standard).

## Deploy note
Railway serves the Mini App on the same PORT — no new service. After deploy,
verify `https://<railway-domain>/webapp` renders and the bot profile shows
the blue «Открыть приложение» button.
