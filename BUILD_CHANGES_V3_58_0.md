# V3.58.0 — money safety and owner-only diagnostics

1. `/diagnostics` and `/platega/check` are owner-only. They open only with
   `?key=<DIAGNOSTICS_KEY>` (new env variable) or from the Mini App as an admin;
   everyone else gets 404. Before, anyone could hit `/platega/check` and create
   real Platega transactions.
2. `spend_peaches` / `consume_photo_credit` deduct with one conditional
   `UPDATE … WHERE photo_credits >= N`: two simultaneous taps can no longer both
   pass the balance check. Negative amounts are rejected.
3. Every top-up in `services/payments.py` adds inside the UPDATE
   (`coalesce(photo_credits, 0) + N`), so a purchase landing during a spend can
   no longer overwrite the balance with a stale value.
4. A duplicate payment callback that loses the race on the unique
   `telegram_charge_id` is logged and ignored instead of raising.
5. New functional tests: `tests/test_v3580_money_safety.py`.
