# AnnaBot V3.38.0 — Come Closer Funnel + New Character Pack

## Bot menu funnels into the Mini App
- The main reply keyboard is now a launcher for the Mini App (owner benchmark: @come_closer_bot screenshots): `📱 Открыть приложение` on its own row, `🍓 Добавить клубничек` + `🖼 Создать картинку` in the middle, `💰 Партнёрка` + `👥 Поддержка` at the bottom.
- Reply keyboards cannot carry URLs, so each button answers with an inline `web_app` button opening the Mini App (with the `PUBLIC_BASE_URL` setup hint when the server URL is not configured).
- Old label keys stay in `KB_LABELS`, so cached reply keyboards from earlier versions keep resolving to their handlers.
- `👥 Поддержка` is now a real ticket flow: the button arms a pending state and the user's next plain text message is forwarded to `ADMIN_TELEGRAM_IDS` (survives restarts via `DialogStore`); commands like `/start` still pass through. The donation appeal moved to `/legal`.
- `📜 Документы` left the reply keyboard (bank compliance is preserved by the `/legal` command, the inline legal menu and the Mini App profile row).

## Mini App — 5 tabs (Come Closer layout)
- Bottom navigation: `👩 Персонажи` / `💬 Чаты` / `🖼 Картинки` / `🛒 Магазин` / `👤 Профиль`.
- Character cards gained a story-hook subtitle (`hook` field from `SCENARIO_HOOKS`) under the name, exactly like the screenshots.
- New `💬 Чаты` tab: per-character rows with the last message preview and time, opens the shared in-app chat view; backed by `GET /webapp/api/chats`.
- New `🖼 Картинки` studio: freeform prompt (up to 800 chars), style (аниме/реализм/фэнтези) and format (квадрат/портрет), advanced mode, personal gallery.
  - `POST /webapp/api/picture` costs 1 photo credit (🍓), charged **only after a successful render** — a failed generation never costs anything.
  - Prompts pass a hard minors/coercion filter and get the standing SFW suffix appended; files are stored per-user under `data/app_pictures/<telegram_id>/` with unguessable server-generated names and served owner-scoped via `GET /webapp/picture/{filename}`.
- `💰 Партнёрка` and `📜 Документы` moved from bottom tabs into full-screen overlays opened from the `👤 Профиль` tab (menu rows), render functions unchanged.

## New characters (incl. the requested «30+» women)
- `Эрика, 38` — мать друга (🌹), `Соня, 22` — подруга детства (🌸), `Вика, 35` — начальница (👠), `Алиса, 27` — учительница (📚), `Мила, 30` — соседка (☕).
- Full profiles in `data/characters/*.json` (personality, boundaries, photorealistic visual identity anchors) + canonical references in `data/references/<name>/` (face + look), wired into `DEFAULT_CARDS`, `SCENARIO_HOOKS` and the Mini App storefront (`_FACE_REFERENCES`).
- Each card opens with a cinematic scenario hook that drops the user straight into her scene.

## Ops
- New endpoints: `GET /webapp/api/chats`, `POST /webapp/api/picture`, `GET /webapp/api/pictures`, `GET /webapp/picture/{filename}`.
- Tests: new `tests/test_v3380_menu_app_static.py`; version pins bumped to 3.38.0; full suite green (fresh SQLite DB per run via `DATABASE_URL`).
