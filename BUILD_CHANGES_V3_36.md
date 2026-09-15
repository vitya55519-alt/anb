# AnnaBot V3.36.0 — Rub & Dollar Prices Next to Every Stars Price

Owner request: «напротив каждой цены звездочек добавь цену в рублях и
долларах, на свой выбор, можешь даже цену поднять или опустить на свой
выбор» — every Telegram Stars price in the product now shows its ruble and
dollar equivalent.

## What ships

### The fiat display engine (config.py)
- `STARS_FIAT_RUB` / `STARS_FIAT_USD` — a price ladder for the common star
  counts (5–50⭐), roughly what Stars cost to top up inside Telegram.
  Dollars are round marketing numbers, not FX quotes.
- `usd_str()` / `fiat_values()` / `fiat_suffix()` — `fiat_suffix(25)` →
  `' · 59 ₽ · $0.75'`. Explicit `rub=`/`usd=` overrides win over the ladder;
  `rub_enabled=False` hides only the rub part (a real charge that is
  currently off — FreeKassa disabled) while the dollar equivalent still
  shows. Unknown star counts fall back to ~2 ₽ / ~$0.024 per Star.
- Premium month dollars reuse the **real** Visa/Mastercard charge
  `FREEKASSA_PREMIUM_PRICE_USD` ($5) — never an invented number. The week
  (`PREMIUM_WEEKLY_PRICE_USD = 1.5`) and the character constructor
  (`CONSTRUCTOR_PRICE_USD = 2.5`) are new marketing-priced env-overridable
  constants; their rub prices stay the real card prices (99 ₽ / 200 ₽).

### Bot (main.py) — fiat next to every ⭐ price
Chat photo offer, quest replay branches, the constructor menu, both Premium
pitch lines and both Premium keyboard buttons, video animation, custom
photo, the photo paywall, all three gallery download texts/buttons, spicy
menus, the gifts menu (incl. the discounted «gift of the day») and the
dates menu now read `25⭐ · 59 ₽ · $0.75` style. The Mini App constructor
options payload carries `rub`/`usd` for the wizard's price note.

### Mini App (webapp_service.py + index.html)
- `api_shop`: every price-list item plus the Premium hero carry
  `rub` + `usd`; `constructor_usd` joins `constructor_rub`;
  `api_invoice_products` adds `usd` to both Premium plans and the rub+usd
  ladder to the photo credit.
- The shop tab renders all three tiers via one shared esc()-safe `fiat()`
  formatter; the wizard price note shows `⭐ 50 · 200 ₽ · $2.5`.

### Legal documents (legal_service.py)
The Platega tariffs (`/tariffs`, RU + EN) list rub + dollar for every
product line — both Premium plans (real card prices), all four photo
tiers, video, story replay, character creation and the gift range.

## Pricing choices made (owner delegated)
Ladder examples: 5⭐→15 ₽/$0.2 · 10⭐→25 ₽/$0.3 · 25⭐→59 ₽/$0.75 ·
40⭐→89 ₽/$1 · 50⭐→99 ₽/$1.2. Premium week $1.5, constructor $2.5.

## Verification
- Runtime probe: helpers, both tariff languages, shop payloads.
- Full suite: 557 passed (10 new tests in
  tests/test_v3360_fiat_prices_static.py; v3340/v3341 pins updated).
