# AnnaBot V3.10.3 — QR Admin Deployment Candidate

## Scope
This is the deployment candidate built on V3.10.2. Existing bot behavior is preserved.

## QR administration
- `🛠 Админка -> 💳 Способы оплаты -> ➕ Добавить QR` remains enabled for configured owners.
- Admin can create multiple QR records without editing source code.
- QR image is uploaded directly to the bot and stored as Telegram `file_id`.
- Name, instruction text and status can be changed from Telegram.
- QR can be replaced, previewed and deleted without a new deploy.
- Metadata persists in PostgreSQL.

## Stars
- Existing Telegram Stars checkout is unchanged.
- The protected system Stars method remains active.

## Future locks
- `🔒 🎬 Оживить фото · скоро` remains visible.
- `🔒 📞 Звонок с Анной · скоро` remains visible.

## Deployment
- Prepared as a clean GitHub/Railway test build.
