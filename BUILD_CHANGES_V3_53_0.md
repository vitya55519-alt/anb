# V3.53.0 — «Собери галерею» (rolling 50-photo gallery sets)

## Что добавлено
Геймификация коллекционирования фото, чтобы поднять вовлечённость и удержание.
Для каждого персонажа **каждое реально полученное фото** (чат бота + чат/«Наедине»/
кружочки/видео в Mini App) увеличивает один счётчик. Каждые **50 фото = один сет
галереи** («квест выполнен» 🏆), затем начинается следующий круг из 50. На
странице персонажа показывается одна полоска **«🖼 N/50 · 🏆 K сетов»**; при
пересечении кратного 50 приложение празднует completion сета.

## Как считается (без записи в горячий путь и без миграций)
Суммируются два **непересекающихся** источника, которые уже пишутся:
- `PhotoDelivery` — все фото, отправленные **ботом** (любая сцена/тип).
- `UserGeneration` — все рендеры **Mini App**, привязанные к персонажу
  (`kind ∈ {photo, circle, video, hot, cosplay}`; безымянная студийная
  `picture` не считается).

Бот никогда не пишет `UserGeneration`, приложение никогда не пишет
`PhotoDelivery` — двойного счёта нет. Отметка «сколько сетов уже объявлено»
живёт в `dialog_sessions` через `DialogStore('gallery_sets')`, поэтому
переживает редеплой на Railway и не требует новой таблицы/колонки.

## Изменения по файлам
- **config.py**: `GALLERY_SET_SIZE` (default 50, env-configurable).
- **services/collection_service.py**: `collected_photo_count()`,
  `gallery_set_progress()` (`count/per_set/sets_done/progress/remaining/complete`),
  `note_gallery_set()` (возвращает число новых завершённых сетов с момента
  последней объявки; fail-silent).
- **services/webapp_service.py**: `api_collection(telegram_id, character_id)` →
  снимок полоски + `just_completed`; fail-silent → `{}`.
- **main.py**: новый GET `/webapp/api/collection` (`_webapp_api_collection`);
  два ответа выдачи фото (chat photo-on-request и chat media) теперь несут
  `set_completed` + `gallery`. Голосовые (`voice`) не считаются и не празднуют.
- **webapp/index.html**: полоска `#charCollectBar` на странице персонажа (под
  шкалой близости), `loadCollection()` при открытии карточки, `renderCollectBar()`
  и тост празднования в обработчиках отправки фото/медиа. Ключи i18n
  `collect_lbl / collect_sets / collect_done` во всех 7 локалях
  (en/ru/es/it/fr/zh/ja).

## Тесты
- `tests/test_v3530_gallery_set_static.py` — 7 static-пинов (конфиг=50, оба
  disjoint-источника и фильтр по kind, математика полоски и DialogStore,
  `api_collection`, роут + `set_completed ≥ 2` + исключение `voice`, полоска и
  празднование в SPA, 7 локалей).
- Паритет базовой строки тестов сохранён.

## Не в scope (отложено)
- Персистентный бейдж в доске достижений за собранные сеты (возможен follow-up).
- Живое приветствие в Telegram для фото, выданных только в боте (определяется
  лениво при следующем открытии страницы персонажа в приложении).
