# AnnaBot V3.42.1 — «Пополнить персики» и «Поддержка» прямо в welcome

## Owner request
«сделай кнопку пополнить персики, в welcome и кнопку поддержка» — the two most
used money/help entry points were only on the main reply keyboard; a returning
user landing on the welcome screen never saw them.

## What changed
- `_welcome_back_rows` now renders, top to bottom: **📱 Открыть приложение** (web_app, when `PUBLIC_BASE_URL` is set) → **🍑 Добавить персиков** → **💰 Партнёрская программа** → **👥 Поддержка** → **📄 Условия + 🔐 Privacy**. Labels come from `KB_LABELS` so RU/EN stay in sync.
- Two new inline callbacks back the welcome screen (it is an `InlineKeyboardMarkup`, so the reply-keyboard handlers could not be reused as-is):
  - `credits:open` → reuses `_send_app_entry` with the same «персики покупаются в приложении — вкладка „Магазин“» intro as the reply `credits_button`.
  - `support:open` → arms `_support_pending` and sends the same «опиши, что случилось, ОДНИМ сообщением» prompt as the reply `support_button`, so the next plain text becomes a ticket to the owner.
- The existing reply-keyboard `credits_button` / `support_button` handlers are untouched (the main menu keeps working and cached keyboards keep resolving).

## Ops
- Tests: `tests/test_v3421_welcome_credits_support_static.py` (welcome rows carry credits/support callbacks, labels localized, `credits:open` reuses `_send_app_entry`, `support:open` arms the pending ticket, reply handlers intact); all 32 version pins bumped to 3.42.1.
