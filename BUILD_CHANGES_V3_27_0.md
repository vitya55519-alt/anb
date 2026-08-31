# V3.27.0 — ruble shop: one-click FreeKassa buttons, tokens, constructor

## Features
1. **One-click premium payment.** The premium keyboard buttons are now
   Telegram url-buttons: pressing one opens the FreeKassa payment page
   directly (the order is created upfront by `_fk_url_button`). No more
   intermediate "here is your link" message.
2. **Payment-system badges.** The RUB button shows `⚡СБП / карта`,
   the USD button shows `Ⓥ Visa / Ⓜ Mastercard` — badges instead of plain text.
3. **Token economy.** New buttons: 1 token = 10 RUB and a 5-token pack (50 RUB).
   Photo animation ("оживить фото") costs 5 tokens (50 RUB) and is
   spent automatically in `_video_gate` before the Stars invoice.
4. **Constructor in rubles.** "Создать своего персонажа" can now be paid
   with 200 RUB (card/SBP) via a `constructor_rub` order; the paid credit is
   consumed in `constructor_buy_cb` and skips the Stars invoice.

## Changes
- `config.py`: `CONSTRUCTOR_COST_RUB=200`, `TOKEN_PRICE_RUB=10`,
  `TOKEN_PACK_SIZE=5`, `VIDEO_TOKEN_COST=5` (all env-overridable).
- `models/app_models.py`: `User.token_balance`, `User.constructor_credit`
  (both `Integer, default=0`; auto-migrated by `_auto_migrate_all_tables`).
- `services/freekassa_service.py`: `create_order` deletes stale (>1h) pending
  duplicates for the same user+product, since url-buttons create an order on
  every keyboard render.
- `main.py`: balance helpers (`get_token_balance/spend_tokens/add_tokens/
  consume_constructor_credit/add_constructor_credit`), `_fk_url_button`,
  badge-labelled url-buttons in `premium_keyboard` / `characters_keyboard`
  (legacy callback buttons kept when no telegram_id), token path in
  `_video_gate`, credit path in `constructor_buy_cb` (unique charge id),
  `_fk_notify` grants by product (`constructor_rub` / `tokens_*` / premium).

## Tests
- `tests/test_v3270_ruble_shop_static.py`: pins config values, model columns
  (static + runtime defaults), one-click url-buttons with SBP/Visa/Mastercard
  badges, token buttons and spend order, constructor credit flow, notify
  product branching, and the stale-pending cleanup.
