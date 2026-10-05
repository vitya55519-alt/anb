# V3.52.1 — donation no longer says «Premium активирован» + free tier 20 → 50

## Owner request
> «я просто поддержал проект, а он пишет «активирован премиум» … можно просто
> «оплата прошла, спасибо, что остаётесь с нами» … зачем премиум-то активировать,
> это ж 50 рублей всего».
> «теперь сделаем не двадцать сообщений в сутки, а без премиума 50».

## 1. Donation confirmation bug (`main.py`, `_platega_callback`)
- **Root cause:** the grant logic had a standalone `if product.startswith('donation_'):`
  that set the thank-you, followed by a SEPARATE `if product == 'constructor_rub':`
  … `elif …` … `else:` chain. A donation skipped the second chain's real branches
  and fell into its final `else` — which is the premium-month default — so the
  donor got «💖 Оплата прошла! Premium активирован на 30 дней».
- **No premium was ever actually granted:** `record_payment` only opens a
  subscription for `premium_month / premium_month_discount / premium_week /
  premium_quarter`; a `donation_*` product just writes the ledger row (which also
  feeds the partner commission). So this was purely the wrong confirmation text.
- **Fix:** the constructor branch is now an `elif` of the SAME chain, so a
  donation matches the leading `if` and can never reach the premium `else`. The
  donation wording is now a plain thank-you: «💜 Оплата прошла! Спасибо за
  поддержку — очень ценно, что ты остаёшься с нами 🥰».
- The shared browser success redirect (`_platega_success`) also dropped its
  «Premium уже включён» claim (it serves every product) → neutral «Оплата
  прошла! Возвращайся в бот — всё уже учтено».

## 2. Free daily message allowance 20 → 50 (`config.py`)
- `FREE_MESSAGES_PER_DAY` default raised 20 → 50. It is the single source: the
  `can_send_message` gate, the Mini App shop «free tier» line, and the legal
  tariff text all read it, so they update together. Premium is still the
  unlimited / $20-equivalent monthly tier.

## Tests
- `tests/test_v3270_ruble_shop_static.py::test_platega_callback_grants_by_product`
  pin updated to `elif product == 'constructor_rub':`.
- `tests/test_v34422_economy_static.py::test_donation_confirm_and_ledger` gained a
  regression pin: the branch after the donation `if` is an `elif` (so a donation
  can never fall through to the premium `else`).
- `tests/test_v3200_retention_static.py::test_retention_config_flags` pin updated
  to `FREE_MESSAGES_PER_DAY", "50"`.
- Full suite: 17 failed / 946 passed / 1 error — exact baseline parity (the 17 +
  error are pre-existing and unrelated).

## Deploy notes
- No schema change.
- `FREE_MESSAGES_PER_DAY` stays env-overridable — set it in Railway to tune
  without a code change.
- `VERSION` not bumped (3.5x line).
