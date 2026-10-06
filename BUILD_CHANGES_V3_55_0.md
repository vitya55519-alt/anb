# V3.55.0 — «Мои видео» + пресеты движения + бейджи сетов

## Что добавлено
Закрывает оба отложенных пункта V3.54.0/V3.53.0.

1. **Пресеты движения в студии 🎬** — чипы под полем промпта: «🎞️ Авто» +
   полный набор из бота (💋 Поцелуй, 😏 Подмигивание, 💨 Оборот, 🥶 Шёпот,
   🖐 Прикосновение, 🔥 Ласка) — решение владельца. Клиент шлёт **только ключ**,
   сервер подставляет готовый промпт из `cloud_video_service.VIDEO_PRESETS` —
   пользовательский текст не формирует движение, когда пресет выбран; без
   пресета остаётся прежнее поведение (свои слова как лёгкая подсказка либо
   спокойный дефолт движка). Сцена-гейтированный sensual-пресет бота в этом
   роуте по-прежнему недостижим (зафиксирован в тестах V3.54.0).
2. **Галерея «Мои видео»** — секция под генератором в видео-режиме: все
   видео, отрендеренные приложением (студия + чат-видео; видеокружки остаются
   в истории чата), новые сверху. Источник — аудит-таблица `UserGeneration`
   (kind='video'), байты — в Postgres `ChatMedia`: `/webapp/media` сам
   восстанавливает файл на диск при первом обращении, поэтому галерея
   переживает редеплой **без новой таблицы/колонки**. Просмотр бесплатен.
3. **Бейджи сетов галереи на доске достижений** — два косметических
   ачивмента (без 🍑/Stars, прежнее owner-решение): «Первый сет» за первые
   50 фото одного персонажа и «Марафонец галерей» за пять сетов суммарно.

## Изменения по файлам
- **services/webapp_service.py**: `api_video_list(telegram_id, limit=40)` —
  select `UserGeneration` (kind='video', filename not null) по created_at desc,
  выдаёт `{file: '/webapp/media/…', prompt, created}`; fail-silent → [].
- **main.py**:
  - `_webapp_api_studio_video`: читает `preset` из тела,
    `motion = VIDEO_PRESETS[preset][1] if preset in VIDEO_PRESETS else (prompt or None)`;
    неизвестный ключ молча = авто; `preset` пишется в `track_event` meta.
  - новый GET `/webapp/api/videos` (`_webapp_api_videos`) — auth как у
    `/webapp/api/pictures` (401), ответ `{ok, videos}`; зарегистрирован рядом.
- **services/gamification_service.py**: `ACHIEVEMENTS` += `gallery_set_first`
  ('Первый сет') и `gallery_set_five` ('Марафонец галерей'), reward `[]`;
  оба в `MISSION_GROUP 'romance'`; CTA первого — существующий live-callback
  `photo_menu:open`.
- **services/collection_service.py**: в `note_gallery_set()` — единственная
  точка обнаружения завершения сета; при новом завершении вызывает
  `unlock_achievement` для обоих бейджей (идемпотентно; порог «5 сетов» —
  сумма заанонсированных сетов по персонажам из DialogStore-штампа). Весь
  хук в try/except: доска не может уронить выдачу фото.
- **webapp/index.html**: `PIC_PRESET` + `VID_PRESETS_UI`/`studioPresetChips()`
  (одиночный выбор, повторный тап = сброс в «Авто», CSS чипов переиспользован
  от языковых), тело запроса видео добавляет `preset`, секция «🎬 Мои видео»
  (`#vidGallery`, сетка `.vgal` 2×9:16 из `<video controls playsinline>`),
  `loadStudioVideos()` заполняется при переключении в видео-режим, при первом
  визите вкладки в этом режиме и после успешной генерации. 9 новых ключей i18n
  (`videos_title`, `videos_empty`, `preset_auto/kiss/wink/turn/whisper/touch/caress`)
  во всех 7 локалях (en/ru/es/it/fr/zh/ja).
4. **Цены Premium + бонус канала** — решение владельца:
   - месячный Premium: **899 → 699 ₽** (PLATEGA_PREMIUM_PRICE_RUB);
   - недельный Premium: **299 → 199 ₽** (PLATEGA_PREMIUM_WEEKLY_PRICE_RUB);
   - display-only USD-тег: **$5 → $8** (PREMIUM_PRICE_USD);
   - бонус за подписку на канал: **30 → 20 🍑** (CHANNEL_SUBSCRIBE_BONUS_CREDITS).
   Все три читаются с env-override: если в Railway заданы
   PLATEGA_PREMIUM_PRICE_RUB / PLATEGA_PREMIUM_WEEKLY_PRICE_RUB /
   PREMIUM_PRICE_USD /
   CHANNEL_SUBSCRIBE_BONUS_CREDITS — переменные побеждают дефолт, их надо
   обновить или удалить в панели перед деплоем.

## Тесты
- `tests/test_v3550_video_gallery_static.py` — 6 static-пинов: запрос
  галереи (kind/порядок/Postgres-path), роут + auth-модель, key-only motion
  (плюс preset в аналитике), косметичность бейджей и единственная точка
  хука с порогом 5, SPA-пины чипов/галереи/заполнения, наличие 9 ключей в
  ≥7 локалях.
- `tests/test_v3540_studio_media_static.py` — pin нейтрального движения
  обновлён на ветку-фолбэк (`else (prompt or None)`), отрицание SENSUAL в
  обработчике студии сохранено и остаётся красным при регрессии.
- `tests/test_v3430_release_static.py`, `test_v34423_custom_peach_static.py`,
  `test_v34421_platega_static.py`, `test_v3201_usd_spoken_circle_tts_static.py` —
  config-пины обновлены на новые дефолты (699/8/20).
- Паритет базовой линии: 17 failed / 966 passed / 1 error (960 + 6 новых).

## Не в scope
- Скачивание видео, фильтры/многоколоночная лента, обложки-постеры (плитки
  грузят metadata нативным плеером).
- Бейджи не дают наград (чистая косметика); отдельная страница «видео бота» —
  только app-видео.
- `VERSION` не трогали.
