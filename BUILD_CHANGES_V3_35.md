# AnnaBot V3.35.0 — Chat in the App + Character Constructor Wizard

Owner request: «сделай так, чтобы человек еще мог общаться в приложении —
нажмет на карточку и у них открывается диалог. Потом каждый пользователь
может создать своего персонажа: лицо, прическа, характер, размер груди,
талии, попы, телосложение, возраст — главное, чтобы он подхватил характер:
если она пошлая, пусть общается как пошлая, если скромная — скромно. И
созданный персонаж пусть будет виден другим. Но и все-таки добавь эту синюю
кнопку "открыть приложение".»

## What ships

### Chat inside the Mini App
- Tapping a character card now opens a **full-screen dialog** instead of just
  selecting her: chat head (photo/emoji, name, «Выбрать» button), scrollable
  message list with user/bot bubbles and timestamps, and a text input.
- `GET /webapp/api/chat` — the shared history (same `messages` table the bot
  chat writes to; the bot and the app are one continuous dialog per
  (user, character)). Limit clamped 1..60, oldest-first.
- `POST /webapp/api/chat` — a message typed in the app goes through the
  **exact pipeline the bot chat uses**: `chat_service.reply()` with memory,
  relationships, adaptation and the persona override. Same gates too:
  - 18+ consent (`has_accepted`) → 403 `consent`;
  - daily free-message limit (`can_send_message`, admins bypass) → 429 `limit`;
  - built-in cards keep storefront gating (`active` free, `premium` needs
    Premium → 403 `premium_required`);
  - **custom personas are public** — anyone can open a dialog with her, only
    the character must exist.
- i18n toasts for consent / limit / locked instead of silent failures.

### Per-user character constructor (app wizard)
- The wizard walks the same `CONSTRUCTOR_STEPS` the bot's inline constructor
  uses, now extended **7 → 11 steps / 46 options**:
  - new: **face** (oval / round / sharp-model / soft), **breast** (small /
    medium / large / very large), **waist** (slim wasp / toned / soft),
    **hips** (neat / round / curvy / very curvy);
  - temperament gains **Скромная и застенчивая** and **Пошлая и развратная**.
- «Характер подхватил общение»: new `TEMPERAMENT_STYLE` dict appends a style
  line inside `build_persona_context`, so **every chat — bot or app — speaks
  in the chosen voice**: a naughty girl writes dirty innuendo in every
  message (без графичности — через намёки), a shy one blushes, answers short
  and quiet.
- `GET /webapp/api/constructor/options` — steps labeled per language
  (new `OPTION_LABELS_EN` / `STEP_TITLES_EN`), price rides along
  (`stars`, `free` for admins).
- `POST /webapp/api/constructor/draft` — validates every step value against
  the declared options, one persona per user (409 `exists`), name ≤ 24 chars,
  then drops the draft into the **same `_constructor_sessions` store** the
  bot wizard uses.
- `POST /webapp/api/constructor/buy` — the identical payment pipeline:
  admins and rub-credit holders finish for free (`consume_constructor_credit`
  → `record_payment(0)`), everyone else gets a Stars invoice link with the
  **same `constructor:<telegram_id>` payload** the chat wizard charges, so
  `pre_checkout` → `successful_payment` finishes her with zero new granting
  code. `_finish_constructor` was refactored `(message, charge)` →
  `(chat_id, charge, telegram_id=None)` to be callable from both pipelines.
- After payment the wizard polls the grid (5s × 18) until the new card with
  the avatar appears.

### Public personas
- Custom characters were already registered as visible `active` cards; now
  the grid marks them: `🎨 сделано пользователем` badge, `💚 моя` for the
  caller's own creation (`custom` / `mine` flags in `api_characters`).
- The avatar route `/webapp/photo/<id>` already serves custom avatars
  publicly — cross-user chat needed only the relaxed chat-send gate above.

### The blue «Открыть приложение» button
- `set_chat_menu_button` text is now **«Открыть приложение»**.
- `PUBLIC_BASE_URL` auto-falls back to Railway's `RAILWAY_PUBLIC_DOMAIN`
  (https:// prefixed) when unset, so the button cannot silently disappear
  on a fresh deploy.

## Files changed
- `services/custom_character_service.py` — 11 steps/46 options,
  `TEMPERAMENT_STYLE`, EN labels, avatar/persona key tuples extended.
- `services/webapp_service.py` — `api_constructor_steps`, `api_chat_history`,
  `custom`/`mine` grid flags.
- `main.py` — 5 new webapp handlers + routes, `_finish_constructor`
  signature refactor, menu button text.
- `config.py` — `PUBLIC_BASE_URL` Railway fallback.
- `webapp/index.html` — chat overlay, constructor wizard, badges, i18n.
- `tests/test_v3350_app_chat_constructor_static.py` — new static suite;
  `test_v3340`/`test_v319` pins updated; 23 old suites widened to 3.35.0.

## Deploy notes
- No migrations (new constructor keys ride in `params_json`).
- No new env vars: `PUBLIC_BASE_URL` still wins if set; Railway's public
  domain is picked up automatically.
- VERSION → 3.35.0.
