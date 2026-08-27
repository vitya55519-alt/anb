# BUILD CHANGES V3.19.6 — FreeKassa card/SBP premium

Owner activated a FreeKassa merchant (merchant id 75666) so users can pay for
Premium with a Russian card or SBP QR code, alongside Stars and Wallet Pay.

## How it works
- `premium_keyboard()` shows a `💳 Premium — N ₽ картой / СБП` button only when
  `FREEKASSA_ENABLED` (all three cabinet secrets configured).
- The `fk:premium` callback creates a `FreeKassaOrder` row and sends the user
  a signed payment link (`pay.freekassa.ru`, signature = MD5 with SECRET1).
- A tiny aiohttp web server (Railway `PORT`, default 8080) starts before
  polling and serves:
  - `/freekassa/notify` — server notification; signature checked with SECRET2,
    then idempotent `pending -> paid` and `record_payment(..., provider='freekassa')`
    grants Premium and the bot messages the user;
  - `/freekassa/success` / `/freekassa/fail` — user-facing redirect pages
    (accept GET and POST, matching the merchant form method dropdowns);
  - `/healthz` — Railway health check.
- Without valid SECRET2 signature nothing is granted, so the endpoints are
  safe to expose publicly.

## Config (Railway Variables)
`FREEKASSA_MERCHANT_ID`, `FREEKASSA_SECRET1`, `FREEKASSA_SECRET2` (ASCII-only
secret words, exactly as in the cabinet), optional
`FREEKASSA_PREMIUM_PRICE_RUB` (default 299) and `PUBLIC_BASE_URL` (the
generated Railway domain used in the merchant form URLs).

## Tests
- New `tests/test_v3196_freekassa_static.py` (6 tests).
