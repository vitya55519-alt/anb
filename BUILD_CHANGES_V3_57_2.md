# V3.57.2 — Приложение ускорено: блокирующие вызовы ушли с event loop

Фидбек владельца: «ускорь приложение, чтобы работало очень быстро, прогружало
ещё быстрее». Мини-приложение (aiohttp) обслуживает все запросы в одном
asyncio-потоке. Любой синхронный вызов — round-trip в PostgreSQL Railway
(десятки мс), upsert `ensure_user`, запись `save_message`, чтение байтов
медиа/диска — **блокировал весь event loop**: пока один пользователь грузил
галерею, все остальные ждали, а загрузка самого SPA ощущалась «тормозящей».

## Что сделано

### 1. Блокирующие вызовы вынесены в рабочие потоки (`main.py`)
Ключевой паттерн версии: каждая блокирующая секция эндпоинта оборачивается в
локальное замыкание (`_boot/_load/_prelude/_deliver/_gate/_finish/_store/_save/_apply/_toggle/_pick_line/_allowed/_catalogue/_prologue`) и исполняется через
`await asyncio.to_thread(...)`; одиночные вызовы уходят напрямую в `to_thread`.
Вынесено ~40+ мест во всех `_webapp_*` обработчиках, в том числе:
- `api_me` (upsert + track_event + сборка профиля), `characters`, `chats`,
  `chat_history`, `select`, `shop`, `gallery(+share/image/save)`, `partner`,
  `photo`, `media/voice/video`, `chat_media`, `chat_turn`, `chat_persona`,
  `story`, `feature` — у последних двух тела синхронные (0 `await`), поэтому
  разведены на тонкий async-враппер + синхронный `_*_impl`, исполняемый в потоке;
- `invoice`/`pay_link` (lang, каталог, Platega `create_order`), `channel_bonus`
  (новый модульный хелпер `_track_channel_bonus`), creator-cabinet/publish/edit/
  delete, achievements, comments, notif-prefs, gift/promo, char_view/like;
- раздача ассетов (`gif/live/card/media/picture/pgal`) — поиск пути и
  `read_bytes` так же уходят из loop.
- `_webapp_chat_gate` вызывается через `to_thread` из текстового, голосового и
  фото-эндпоинтов (4 чтения БД на каждый ход чата).

### 2. Ёмкость потоков и пула согласована
- **`main.py` → `_start_web_server`**: после `runner.setup()` ставится
  `ThreadPoolExecutor(max_workers=16, thread_name_prefix='offload')` как дефолтный
  executor loop — раньше `to_thread` делил всего 5 потоков на все эндпоинты.
- **`services/db.py`**: для PostgreSQL добавлен пул
  `pool_size=10, max_overflow=20, pool_recycle=1800` (+ `pool_pre_ping`), чтобы
  16 потоков не голодали пул на дефолте 5+10; sqlite не тронут.

### 3. Ускорена загрузка самого SPA (`webapp/index.html`)
- `<link rel="preconnect">` + `<link rel="preload" as="script">` для
  `telegram-web-app.js`: DNS/TLS прогреваются и загрузка SDK стартует во время
  парсинга HTML, а не на блокирующем `<script>`; скрипту проставлен
  `fetchpriority="high"`.
- Бут уже идёт параллельно (`loadMe()` + `loadCharacters()` +
  `checkConstructorStatus()` независимо), второстепенные вкладки — лениво, канал
  — по таймеру; все `<img>` уже `loading="lazy"` (доп. правок не потребовалось).

## Тесты
- Пины статических тестов переведены на новые формы offload (там, где литерал
  осознанно поменялся): `test_v3570` (форма gate/`synthesize_bytes`/`save_chat_media`),
  `test_v3350` (`api_constructor_steps, request.query.get(`), `test_v3340`
  (characters через `to_thread`), `test_v3380/v3400/v3430/v3432/v3435/v34411/
  v34421/v3474/v3483/v3501/v3550/v3556`.
- Прогон: **12 failed / 1096 passed / 1 error** — ровно базовый набор V3.57.1
  (v3121, v319×3, v3200, v3370, v3390, v3410×3, v3437×2, error v392); V3.57.2
  не добавила ни одного падения.

## Что не трогали
Длительные генерации (`picture_generate`, `studio_video`, `pipeline_photo`,
`constructor_*`) — их стоимость это внешний AI-вызов, а не БД; выносить в поток
тут нечего и нельзя (там живые `await`).
