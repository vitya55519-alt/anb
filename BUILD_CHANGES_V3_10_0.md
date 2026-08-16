# V3.10.0 — Telegram Character Cards Admin

## New
- Added persistent `character_cards` PostgreSQL/SQLite table.
- Character cards are now data-driven instead of hard-coded in Telegram UI.
- Added owner-only Telegram admin panel: `/admin` or `🛠 Админка`.
- Admin can edit each girl's public card directly in Telegram:
  - display name
  - age (18–99)
  - short bio/description
  - public status (`active`, `soon`, `locked`, `premium`)
  - visibility in the Characters menu
  - card cover photo using a Telegram photo/file_id
  - reset to built-in defaults
- Card cover uploads reuse the existing image moderation guard before becoming public.
- Admin-only `/admin` command is installed with a per-chat Telegram command scope when `ADMIN_TELEGRAM_IDS` is configured.
- Added dynamic public `👩 Персонажи` menu and full card preview for Anna/Emily.
- Legacy V3.9.x Anna/Emily callback buttons remain compatible.

## Important behavior
- Editing a public card does **not** rewrite personality, memory, relationship state, or Photo Engine identity.
- Card status is presentation metadata only in this release; it does not switch the active chat engine away from Anna.
- Values are stored in the database, so Railway redeploys do not erase edits.

## Admin usage
1. Ensure your Telegram numeric ID is in Railway variable `ADMIN_TELEGRAM_IDS`.
2. Redeploy.
3. Send `/start` once to refresh the persistent keyboard; admins get `🛠 Админка`.
4. Open `🛠 Админка` → `👩 Карточки девушек`.
5. Select Anna or Emily and edit fields with the inline buttons.
6. For a card cover, press `🖼 Фото` and send the desired image.
