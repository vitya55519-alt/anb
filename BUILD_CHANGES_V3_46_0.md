# AnnaBot V3.46.0 — награды за достижения + воронка «Миссии»

`unlock_achievement()` раньше только записывал строку в БД и не давал ничего,
а каталогов достижений было три, ничего не знающих друг о друге. В этом релизе
введена **единая модель награды** с идемпотентной раздачей и **воронка миссий**
со своими экранами в боте (`/миссии`) и в приложении (новая bottom-nav вкладка).

## Принципы и guardrails
- Награды **только трёх видов**: `voucher` (свидание), `scene` (sealed-сцена из
  существующего приват-контента), `badge` (косметика). 🍑 и ⭐ **не начисляем**
  (решение владельца) — чтобы не размывать 20🍑-создание и платный фото-цикл.
- Идемпотентность: `unlock_achievement` вставляет строку один раз
  (`existing → return False`); раздача происходит строго после успешного
  commit, поэтому повторный триггер не может выдать награду дважды.
- Без дублей: семидневный стрик уже выдаёт `grant_free_date_voucher`, поэтому
  streak-достижения не дают ваучер повторно.
- Единый стор: `scene`-награды пишутся в `user.achievements` CSV (его читает
  `get_unified_progress`) — анлок виден на доске и в боте, и в приложении.

## 1. Backend: модель награды + раздача (единый источник)
- `ACHIEVEMENTS` стали тройками `(name, description, reward)`, где `reward` —
  список перков `(kind, payload)`:
  - `seven_day_streak`/`hundred_messages`/`photo_collector`/`date_collector`/
    `anniv_7`/`anniv_90` → `scene`; `anniv_30` → `scene`+`voucher`;
  - `ten_dates` → `voucher`; остальные → `badge` (пустой список);
  - `fully_nude` зарезервирован под самый редкий анлок (`anniv_90`).
- `_grant_achievement_reward()`: `voucher` → `grant_free_date_voucher()`;
  `scene` → `private_photo_service.grant_achievement(id, key)`; `badge` → ничего.
- `private_photo_service.ACHIEVEMENT_SCENE_UNLOCKS` + `unlocked_scene_categories()`;
  `consume_free_private_photo` уважает ачивку-анлок **до** дневного лимита и
  Hot Pass, не сжигая счётчик.
- `get_unified_progress` отдаёт чип `reward` на каждый item.
- Легаси-каталог `retention_features_service.reward_stars` помечен
  неавторитетным (в единую доску не входит, награды не раздаёт).

## 2. Бот: экран `/миссии` + нотификация о награде
- `get_missions()` — роадмап по группам (start → romance → creator) со статусом,
  прогрессом, чипом награды и CTA на существующий callback.
- `@dp.message(Command('missions'))` + callback `missions:view`; кнопка
  «🎯 Миссии» в меню приват-фото.
- `try_unlock()`/`achievement_unlock_text()` + `_notify_unlock()`: сообщение
  «🏆 Достижение открыто … · награда: …» только при реально новом анлоке.
- Хуки: `first_creation` (после `_finish_constructor`), `community_publish`
  (на аппруве в `charmod_cb`, автору), `views_100` (пересечение 100 просмотров в
  `_webapp_api_char_view` → автору), `first_video` (в `_run_video_background` и
  `_run_circle_background`), `first_spicy_photo` (успешная генерация в
  `private_photo:go`).

## 3. Приложение: API миссий + своя bottom-nav вкладка
- `webapp_service.api_missions()` + роут `/webapp/api/missions`; бот-callback'ы
  отображаются в существующие экшены SPA (`construct`/`shop`/`creator`).
- `index.html`: кнопка `data-tab="missions"` (🏅), секция `#tab-missions`,
  кейс в `lazyLoadTab`, флаг `_missionsLoaded`, `loadMissions()` с рендером
  строк/прогресса/наград/CTA и `_missionAction()`.
- CSS `.misrow`/`.mis-group`/`.miscta`.

## 4. i18n + polish
- Метка «Миссии» в `NAV_LABELS` (ru/en/es/it/fr/zh/ja, индекс 4) и
  `missions_title` во всех семи языковых блоках; заголовок вкладки из `L`.
- Баннер анлока в приложении: тост о миссии, открывшейся с прошлого визита
  (`localStorage.anbMissionsSeen`; первый заход только сеет список).

## Что НЕ менялось
- Никаких начислений 🍑/⭐; экономика 20🍑-создания и платных фото не затронута.
- `retention_features_service` не удалён — лишь перестал быть источником наград.
- Пуш в origin — только по явному запросу.

## Проверки
- `tests/test_v3460_achievements_rewards_static.py` — модель награды и раздача,
  каталог миссий, экран бота + хуки, API/вкладка приложения, i18n и баннер.
- `py_compile` затронутых файлов; `node --check` инлайн-JS `index.html`.
- Полный pytest: **17 failed / 850 passed / 1 error** — паритет с базлайном
  (17 — легаси-статик-пины + collection-артефакт `test_v392_bulk_library`);
  новые тесты только добавлены, регрессий нет.
- `test_v3435::test_seven_interface_languages_are_wired` перенастроен на 6-слотовые
  массивы `NAV_LABELS` — легитимная смена контракта (новая bottom-nav вкладка),
  а не починка регрессии.
