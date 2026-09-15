# AnnaBot V3.40.0 — Living Storefront, Admin Analytics & Come Closer Main Menu

## Main reply keyboard like the Come Closer menu (owner screenshot)
- The funnel now matches the benchmarked menu row-for-row: **📱 Открыть приложение** (a real `web_app` tile — the teal direct launch), **🍑 Добавить персиков** and **🖼 Создать картинку** each on their own full-width row, **💰 Партнёрка + 👥 Поддержка** paired at the bottom (`MAIN_KB_ROWS` in `services/ui_lang.py`).
- Old label handlers stay alive, so cached reply keyboards from earlier versions keep working.

## Admin: user statistics screen
- «📊 Статистика» is now a real RU user-statistics report: total/new (24h, 7d), active (24h, 7d), **Premium active**, user messages (24h, 7d), media mix (photos/circles/videos 24h), studio success rate, D1/D7 retention, Stars 30d + photo cost, and a **top-5 character leaderboard** (7d).
- New `admin_snapshot()` fields: `new_24h`, `premium_active`, `messages_7d`, `circles_24h`, `videos_24h`, `top_characters`.

## Admin: provider failure counters («счетчик отказов»)
- New `provider_stats` table + `services/provider_stats_service.py`: every engine attempt in the media chains bumps `ok`/`fail` with the last error — `photo/seedream_edit`, `photo/seedream_t2i`, `photo/gemini`, `video/*`, `circle/*` (bot dialog and Mini App chains alike).
- New admin screen «🩺 Отказы» (`admin:providers`) renders the table in one tap; counters never raise into the pipelines they observe.

## Storefront: view counter («👁 427k» badge)
- New `character_stats` table; opening a character page in the Mini App bumps the counter (`POST /webapp/api/char_view`, initData-authed) and the grid badge refreshes in place.
- Cards carry a compact «👁 43k» pill (top-right); the selected ❤️ badge moved to the bottom-left corner.

## Storefront: living card tiles («вместо фото гифки»)
- Every built-in heroine got a pre-rendered **looping Ken-Burns preview** (`data/references/<name>/card_preview.webp`, 16 frames, perfect sinusoidal loop) — animated «гифки» in the grid via `GET /webapp/gif/{id}`; animated WebP keeps them 120–320 KB instead of 1.2–1.7 MB GIFs and degrades to a still frame on ancient WebViews.
- Custom personas and missing assets fall back to the static photo; the character page strip still shows the canonical face/look shots.

## Ops
- New endpoints: `GET /webapp/gif/{character_id}`, `POST /webapp/api/char_view`; new tables `character_stats`, `provider_stats` (auto-migrated).
- Tests: `tests/test_v3400_admin_stats_views_gif_static.py` (menu layout, counters + hooks, stats screen, view badge chain, animated tiles); stale pins updated (v3380 menu rows, v3340 template whitelist); version pins bumped to 3.40.0.
