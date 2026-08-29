# Build Changes — v3.23.0 (Spicy Monetization Pack)

Version: **3.23.0**
Build date: **2026-08-29**
Owner request: **give the audience that comes for sexualized content three paid products: hot photo sets outside the daily limit, private scene-gifts with an 18+ photo finale, and a paid fantasy constructor (user describes a scenario — the bot assembles the set).**

---

## Context / Why this release

A large part of the audience comes to the bot specifically for sensual content. Before v3.23.0 the only paid 18+ path was the generic "custom photo" invoice — no storefront, no progression, no impulse-buy products. This release adds a dedicated **🔥 Приватное** section inside the photo menu with three products, each gated by relationship level and the one-time 18+ confirmation, all delivered **outside the free daily quota**.

---

## What was done

### 1. New service `services/spicy_service.py`
- `SPICY_SETS` catalog (3 hot sets): Будуар (lingerie, lvl 5, 15⭐), Дразнит (tease, lvl 6, 20⭐), Только для тебя (nude, lvl 6, 25⭐). Each carries RU/EN name + narration + mood.
- `PRIVATE_GIFTS` catalog (3 private gifts): Шёлковый халатик (15⭐), Кружевной комплект (20⭐), Ванна при свечах (25⭐) — each grants an affection delta and ends with a private-scene photo set (like dates, but intimate).
- `FANTASY_COST_STARS` (env-overridable, default 30⭐) and `FANTASY_MIN_LEVEL = 6`.
- `parse_fantasy(text)` — keyword→PhotoRequest mapping over whitelisted regexes (scene / lingerie color & style / location / mood / time of day). **Raw user text never enters the image prompt** — every value is a fixed, moderation-safe string, so users cannot smuggle prompt payloads to the providers.

### 2. Paid delivery mechanics (`main.py`)
- New usage path `delivery_type='paid'`: counted into `paid_used` only — it never spends the free daily quota and never consumes photo credits; the set is pure fresh AI (community pool/library skipped, so 18+ frames stay private).
- `_start_photo_background` / `_run_photo_background` gained keyword args `charge / amount / product`. On any failure (permission, generation error, budget guard, busy job) `_maybe_refund_paid_photo` refunds the Stars automatically and records the refund. Free flows are untouched (no charge id ⇒ old behavior).
- The image budget guard now also covers paid sets — money is never taken during a provider outage.

### 3. Storefront and payments
- Photo menu (`photo_keyboard`) gets a **🔥 Приватное — горячие сеты** entry from level 5 (RU/EN label).
- `_spicy_menu_text` / `_spicy_menu_keyboard` render the section: sets, gifts and the fantasy button with level locks (`spicy:locked:<lvl>` alerts reuse the relationship-scale wording, RU/EN).
- Callbacks: `spicy:menu`, `spicy:set:<id>`, `spicy:gift:<id>`, `spicy:fantasy`, `spicy:locked:<lvl>` — each re-checks level and 18+ before sending an invoice.
- `pre_checkout` validates `spicy:<id>`, `pgift:<id>` and `fantasy:start` payloads: amount vs catalog, level gate, `is_adult_confirmed`.
- `successful_payment`:
  - `spicy:` — records `spicy_set`, sends narration + voice note, launches the set with `charge=charge` for auto-refund;
  - `pgift:` — records `private_gift`, applies the affection/intimacy delta via `record_user_message`, narration + voice note + 18+ photo finale;
  - `fantasy:start` — records `fantasy`, stores `(charge, amount)` in `_fantasy_pending` and asks for the scenario.
- Fantasy input: the next text message is intercepted at the top of `text_message` (before the chat catch-all) by `_handle_fantasy_input` → `parse_fantasy` → paid set generation; too-short input asks for more detail without consuming the purchase.

### 4. Tests and pins
- New suite `test_v3230_spicy_monetization_static.py` (12 tests): catalogs, fantasy parser keyword extraction + prompt-injection non-leakage, pre_checkout validation for all three products, paid-delivery quota isolation, auto-refund wiring, menu entry point, handler gates (level + 18+ before invoice), fantasy interception order.
- Version pins updated: test_v3201 / test_v3210 / test_v3220 accept 3.23.0.

### 5. Versioning and migration
- `VERSION` bumped to **3.23.0**.
- No DB changes: products are catalogs, purchases reuse `StarTransaction`; `FANTASY_COST_STARS` is env-overridable.

---

## Verification

- `python -m pytest tests -q --ignore=tests/test_v392_bulk_library.py`
- `python -m pytest tests/test_v3230_spicy_monetization_static.py -q`
- `py_compile` clean on main.py and services/spicy_service.py.

---

## Operational notes (Railway)

- Prices are editable without a redeploy only via the `FANTASY_COST_STARS` env var; set/gift prices live in the catalog (edit + redeploy).
- Admins can test instantly: the spicy menu has no admin shortcut yet — buy with Stars (admin purchases are real charges) or raise a test user's level via the admin panel.
- The refund path mirrors the video pipeline (`refund_star_payment` + `record_refund`); failed paid sets never keep the money.
