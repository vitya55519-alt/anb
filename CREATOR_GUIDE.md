# Creator controls

- `/testlevel` — opens button panel for levels 1–6.
- Level 6 is a committed-relationship simulation; it does not change the real DB relationship.
- `📸 Проверить фото` opens the normal photo selector under the currently simulated level.
- Normal users do not see test commands in `/start`.

## Photo behavior

Photos are now part of the conversation: a direct request such as “покажись” can trigger a photo, while ordinary contextual mentions have a lower chance of doing so.

The generator keeps a fixed identity layer (face, hair, body proportions) and changes scene attributes separately.

## Proactive messages

After about 48 hours of inactivity, Anna may send one short spontaneous message. The scheduler marks the user as contacted so it does not send repeatedly every hour.

## Important deployment setting

Set `ADMIN_TELEGRAM_IDS` to your Telegram numeric ID.
