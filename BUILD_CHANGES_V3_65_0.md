# V3.65.0 — peaches ×100

Owner: «сделаем не x10, а x100, чтобы это прям вау было». Every peach amount is multiplied by `PEACH_SCALE = 100`; ruble and Stars prices do not change, so nobody gains or loses value.

- Prices: chat photo 200 🍑, «Раздеть» 300 🍑, constructor 300 🍑, studio picture 1000 🍑, studio video 2000 🍑, status change 500 🍑, dates in the app = their Stars figure × 100.
- Grants: daily gift 100 🍑 (day 7: 300, cap 1500), channel bonus 2000, welcome code ANNA5 500, referral bonuses, streak rewards and Premium gifts ×100.
- Packs: 1000 🍑 (50⭐ / 99 ₽), 3000 🍑 = 2500 + 500 в подарок (125⭐ / 249 ₽), 10000 🍑 = 7000 + 3000 в подарок (350⭐ / 699 ₽). The old −16% / −29% badges became «+500 🎁» / «+3 000 🎁» — the same discount, told as a gift.
- Custom tile: sold in steps of 100 🍑 at the small-pack rate. The order key `peach_custom_<units>` counts units of 100, so an order created before the deploy still grants the right amount. The app now shows the real price (it used to show a hardcoded ×10 that did not match the charge).
- One-time migration (`services/db.py::_rescale_peaches`): user balances, promo-code nominals and author earnings ×100, guarded by an `app_migrations` row inserted in the same transaction, so it never runs twice.
- Env overrides stay in the OLD unit and are scaled in `config._peach_env`, so values already set on Railway keep their meaning.
- Card/SBP invoices for packs were titled «🪙 Токены»; now «🍑 N персиков».
