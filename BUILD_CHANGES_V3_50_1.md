# V3.50.1 — Fix: app-chat «Задание» button NameError

## Owner report
> «Кнопка задание в чате с персонажем не работает.»

## Root cause
A V3.49.0 regression. The GET feature endpoint's daily-quest fall-through
branch (`main.py::_webapp_api_feature_impl`) calls
`couple_service.daily_quests_state(...)`, but `couple_service` was never
imported inside that function — unlike the POST action branch and the bot
handler, which each do a local `from services import couple_service`.

At runtime, `kind == 'quest'` raised `NameError`, the V3.48.3 exception
wrapper caught it and returned `{'ok': False, 'error':
'temporarily_unavailable'}`, `openFeature` retried once and failed again, so
the sheet showed «Не получилось ответить — попробуй ещё раз». The static
suite could not catch it (it never imports the runtime).

## Fix (`main.py`)
- Added the local `from services import couple_service` immediately before the
  daily-quest GET branch. No signature changes; the import is scoped to the
  fall-through path only (every other `kind` returns earlier).

## Test (`tests/test_v3501_quest_button_import_static.py`)
- Static regression pin that slices each feature function body and asserts the
  `couple_service` import exists AND precedes its first use
  (`daily_quests_state` in GET, `claim_quest` in POST) — the exact class of bug
  that slipped through.

## Deploy notes
- No schema change, no `VERSION` bump (3.4x line).
- Ships as a standalone hotfix commit ahead of the V3.51 quest-feature work.
