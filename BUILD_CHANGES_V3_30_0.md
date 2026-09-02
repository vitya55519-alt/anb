# V3.30.0 — FreeKassa REST API, чистое фото-меню, косплей за токены

## 1. FreeKassa через REST API (не SCI)

Требование владельца: интеграция обязательно через API (`https://api.fk.life/v1/`,
JSON), разделы документации 1.4, 1.7, 2/2.1–2.3, createOrder.

- `services/freekassa_service.py`:
  - `FK_API_BASE = 'https://api.fk.life/v1'` — все запросы JSON POST сюда;
  - `_api_signature()` — подпись запроса по докам 2.2: ksort параметров,
    значения через `|`, HMAC-SHA256 на API-ключ кассы;
  - `_nonce()` — monotonic nonce (мс), всегда больше предыдущего;
  - `_server_ip()` — публичный IP сервера (ipify/ifconfig, кэш 1 час,
    override `FREEKASSA_SERVER_IP`): orders/create блокирует 127.0.0.1,
    а Telegram не отдаёт боту IP клиента;
  - `_default_payment_id()` — кэш `POST /currencies` (первая включённая
    платёжная система под валюту счёта);
  - `create_api_order()` — `POST /orders/create`: shopId, nonce, signature,
    paymentId (наш order id), `i` (способ оплаты), `email` = `<telegram_id>@telegram.org`,
    `ip`, amount, currency + success/failure/notification URL; ссылка на оплату
    берётся из поля ответа **`location`** и отдаётся клиенту.
- `config.py`: `FREEKASSA_API_KEY` (ключ из кабинета, вкладка «API ключ кассы»),
  `FREEKASSA_API_ENABLED`, `FREEKASSA_SERVER_IP`. Без API-ключа поведение
  прежнее (SCI-ссылка), так что деплой без ключа не ломает оплаты.
- `main.py`:
  - клавиатуры больше не создают ордер на каждый рендер: вместо url-кнопок —
    callback-кнопки `fkapi:<product>:<currency>[:<pay_id>]` (`_fk_pay_button`);
  - новый хендлер `fkapi:` создаёт ордер, зовёт API и присылает пользователю
    ссылку `location`; если API недоступен (нет ключа/IP/ошибка) — фолбэк
    на прежнюю SCI-ссылку, оплата не теряется;
  - отдельная кнопка **⚡ Premium · SBP QR** с `i=44` (приём через QR/СБП);
  - legacy-хендлеры `fk:premium` / `fk:premium_usd` тоже сначала пробуют API.
- Вебхук `/freekassa/notify` и подпись оповещения не тронуты: MD5
  `MERCHANT_ID:AMOUNT:SECRET2:MERCHANT_ORDER_ID` (доки 1.4/1.7) уже соответствовал.

## 2. Убраны кнопки «Обнажённая» и «Дразнит»

- `PHOTO_MENU_ORDER` больше не содержит `nude`/`tease`: провайдеры изображений
  модерировали их в HTTP 422 почти всегда (скриншот владельца).
- Сцены, подписи и реестры photo_service оставлены — старые библиотечные фото
  и выдача по текстовому запросу работают как прежде.

## 3. Косплей-фотосет за 10 токенов

- Новая сцена `cosplay` (SCENES/SCENE_LEVELS=3/SCENE_GROUP/AUTO_CAPTIONS).
- `COSPLAY_COSTUMES` в main.py: горничная, медсестра, кошка-герл, банни,
  эльфийка, ведьмочка, супергероиня, полицейская — полностью одетые образы.
- Кнопка «🎭 Косплей-фотосет — 10🪙» в фото-меню с 3 уровня; пикер костюмов,
  списание `COSPLAY_TOKEN_COST` (env-тюнинг) перед генерацией, возврат токенов,
  если джоба не стартовал (занят/бюджет-гард).

## Тесты

- `tests/test_v3300_fk_api_cosplay_static.py` — пины API-слоя (база, i=44,
  HMAC-вектор подписи, location, email/ip, nonce), меню без взрослых кнопок,
  косплей-флоу; 412 passed.
- Обновлены пины: test_v3181 (меню), test_v3270 (кнопки), test_v3261 и
  версионные кортежи v3201–v3260.
