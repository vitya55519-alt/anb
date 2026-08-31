# V3.26.2 вЂ” FreeKassa order crash: BIGINT telegram_id

## Incident
Pressing the card/SBP premium button crashed the order INSERT:
`sqlalchemy.exc.DataError (psycopg.errors.NumericValueOutOfRange) value out of range`
on `INSERT INTO freekassa_orders (telegram_id, ...)`. The owner's Telegram ID
(8 267 849 550) exceeds the 32-bit INTEGER maximum (2 147 483 647); the column
was created as `Integer` in v3.19.6.

## Fix
- `models/app_models.py`: `FreeKassaOrder.telegram_id` is now `BigInteger`.
- `services/db.py`: new `_widen_freekassa_telegram_id()` runs on startup and,
  on Postgres only, executes
  `ALTER TABLE freekassa_orders ALTER COLUMN telegram_id TYPE BIGINT`
  when the live column is still 32-bit (idempotent; skipped on SQLite and when
  the table/column is absent or already BIGINT). Existing rows are preserved.

## Tests
- `tests/test_v3262_freekassa_bigint_static.py`: pins the model type, the
  startup migration, and a runtime INSERT/read-back of telegram_id 8267849550.