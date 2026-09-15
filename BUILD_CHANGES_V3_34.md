# AnnaBot V3.34.0 — Functional Mini App: Stars Purchases + Character Selection

Owner feedback after v3.33.1: «управление через команду открывает? но там
вообще ничего сделать нельзя? надо что был полный функционал» — the storefront
was read-only. v3.34.0 makes it act.

## What ships

### Shop — buy right in the app
- **Premium · 30 дней — ⭐ 500** — big CTA button on the Premium hero card.
- **+1 фото-кредит — ⭐ 25** — new standalone product, buy button on its own
  row. One payment = one photo credit on the account, spent the next time the
  user asks her for a photo in chat.
- Flow: button → `POST /webapp/api/invoice` (initData HMAC auth) →
  `bot.create_invoice_link(..., currency='XTR')` → frontend calls
  `tg.openInvoice(link)` → Telegram's native Stars payment sheet →
  `successful_payment` arrives at the bot **as a normal payment message**, so
  the exact same `pre_checkout_query` / `successful_payment` handlers grant
  it as a chat purchase. No new granting code, no new money paths.
- New payload `photo_pack`:
  - `pre_checkout_query`: `ok = amount == PHOTO_COST_STARS`;
  - `successful_payment`: `record_payment(tid, 'photo', ...)` → +1 credit
    (the same product record a chat photo purchase writes), bilingual reply
    sent to the user's bot chat.
- The `premium_month` reply is now bilingual too (it was RU-only).
- The rest of the price list stays informational — those products need chat
  context (an offer, a delivery, a wizard) and can't be sold standalone yet.

### Characters — select from the grid
- Tapping a card → `POST /webapp/api/select` → the **same rules as the
  in-chat «Персонажи» buttons**: `active` cards select freely, `premium`
  cards require Premium (403 → the app toasts and opens the shop tab), other
  statuses stay locked.
- The grid re-renders with the new ❤️ marker; `/settings`-style profile
  refreshes (`loadMe`).
- `GET /webapp/api/characters` now accepts optional `init_data` — with a
  valid signature it marks the caller's selected girl, so the marker survives
  reloads after purchases/selections.

### Frontend plumbing (`webapp/index.html`)
- `buy(productId)` — invoice fetch, `tg.openInvoice` with paid/failed/
  cancelled handling, busy-state on buttons, post-payment refresh of all
  tabs; guards against running outside Telegram (`openInvoice` undefined).
- `selectCharacter(el)` — optimistic gate + POST + re-render + toast.
- `toast()` element (fixed top, `textContent` only — no HTML injection).
- Purchase buttons are driven by the backend `shop.purchases` list, so
  prices/titles can't drift from what the API charges.
- All dynamic strings still go through `esc()`; the template-literal audit
  is enforced by `test_no_unescaped_backend_strings_in_templates`.

## Verification
- Static: `tests/test_v3340_webapp_actions_static.py` (9 tests) — product
  declarations, invoice/select route contracts, payment-flow wiring, frontend
  calls, template escaping audit.
- Runtime probe: invoice products RU/EN (500⭐ `premium_month`, 25⭐
  `photo_pack`), shop purchases, initData HMAC (genuine accepted / tampered
  rejected), photo_pack grant `credits 0 → 1`, premium grant (+30 days,
  +12 credits), selected marker.
- aiogram 3.20.0 `Bot.create_invoice_link` confirmed present.
- Full suite: 514 passed.

## Deploy note
Nothing new to configure — same Railway app, same PORT. After deploy, open
the app via `/app` or the profile button: the shop now has a pink
«⭐ 500 — Купить» button and a «Купить» on the +1 photo credit row; tapping a
character card selects her (premium girls redirect to the shop unless
Premium is active).
