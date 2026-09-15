# AnnaBot V3.32.0 — Legal Pack for the Payment Partner (Platega / СБП)

Owner context: the Platega manager's requirements for bank approval — privacy
policy, user agreement, support contacts, actual prices/tariffs, all
permanently reachable from the bot, plus the temporary check word «чекап».

## Full legal documents — `services/legal_service.py`
- `PRIVACY_POLICY` — adapted from the partner's telegra.ph template; sections:
  общие положения, сбор информации (what the bot actually stores), передача
  третьим лицам, хранение/защита (+ `/reset`, `/delete_me`), отказ от
  ответственности, изменения, контакты (`/support`).
- `USER_AGREEMENT` — adapted template: 18+, вымышленные AI-персонажи, AS IS,
  законность, интеллектуальная собственность, ограничения, платежи и возвраты
  (24h refund window, chargeback ban), ссылка на Политику, тикет-поддержка.
- Texts deliberately contain NO ИП/ООО/ИНН data (partner's compliance rule);
  service identity is `телеграм-бот AnnaBot (@come_closer_bot)` — the username
  is env-configurable via `LEGAL_BOT_USERNAME`.
- Revision date: 15 сентября 2026 г.; `LEGAL_VERSION = '2026-09-15'`.

## Always-visible access points (bank review requirement)
- New full-width reply-keyboard row «📜 Документы» / «📜 Documents»
  (`ui_lang.py` KB_LABELS + MAIN_KB_ROWS) — permanent, on the main keyboard.
- `/legal` command + `BotCommand` entry «Документы и цены».
- Both open an inline menu with four buttons: Политика конфиденциальности,
  Пользовательское соглашение, Цены и тарифы, Поддержка
  (callbacks `legal:privacy|terms|tariffs|support`).
- `/terms` and `/privacy` now send the FULL documents instead of one-line
  digests; the /start consent buttons «Условия»/«Privacy» do the same.
- Long documents are split on paragraph boundaries (`split_legal_text`,
  3500-char chunks) to respect Telegram's 4096 limit.
- English users get an EN menu/tariffs/support; the governing legal texts stay
  Russian with a short EN notice above them.

## Цены и тарифы — live rendering
- `tariffs_text()` renders prices straight from config constants (Premium
  Stars/₽, photo 25⭐, custom 40⭐, video 50⭐, gallery 30⭐, quest replay 10⭐,
  constructor 50⭐/200₽, gifts 3–50⭐ with the daily −30% rotation, free
  quotas), so env overrides never make the document stale.

## Support contacts (partner: no groups — ticket system/username/email)
- The in-bot ticket system satisfies the requirement: `/support` (general) and
  `/paysupport` (payment/refunds, 24h window) forward directly to the owner.
- `support_text()` documents both plus `/delete_me` and `/reset`.

## Consent version bump
- `TERMS_VERSION` / `PRIVACY_VERSION` → `2026-09-15`: existing users re-confirm
  the updated documents once on their next `/start` (standard practice when
  the legal texts change).

## Temporary
- Code word «чекап» on the legal menu (`LEGAL_CHECK_WORD`) for the approval
  period. Remove it after the cashier registration is done.
- The channel-side cleanup (ИП/ООО/ИНН info, all languages) is manual work in
  the Telegram channel — nothing of that kind exists in the repo.

Platega integration itself (СБП НСПК 14% / crypto 5%) is NOT part of this
build — it starts after the bank approves the project.
