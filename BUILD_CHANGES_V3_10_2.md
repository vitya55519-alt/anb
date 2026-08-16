# AnnaBot V3.10.2 — Payment Admin + Future Features Locks

## Telegram admin: payment methods
- Added `💳 Способы оплаты` to `/admin`.
- Added persistent `PaymentMethod` rows in PostgreSQL.
- Built-in `Telegram Stars` method is protected and stays active for Telegram digital checkout.
- Admin can add arbitrary QR methods or HTTPS provider links without changing code.
- QR image is saved as a Telegram `file_id`; replacing it requires only sending a new image in the admin chat.
- External methods can be renamed, documented, marked active/disabled/soon, previewed, and deleted.
- External methods are intentionally admin-managed/off-platform placeholders and are not offered as substitutes for Stars for digital goods inside Telegram.

## Payment support
- Added `/paysupport <problem>` which forwards the user's payment issue to every configured `ADMIN_TELEGRAM_IDS` owner.

## Future feature locks
- Added visible-but-locked `🎬 Оживить фото · скоро`.
- Added visible-but-locked `📞 Звонок с Анной · скоро`.
- Both buttons currently show a locked/coming-soon alert only.

## Database
- New table: `payment_methods`.
- `Base.metadata.create_all()` creates it automatically on Railway/PostgreSQL at startup.
