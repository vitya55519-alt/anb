# v3.29.0 — персистентные диалоговые мастера

Дата: 31.08.2026 · Тип: надёжность / фундамент масштабирования (шаг 2 из 3)

## Проблема
Многошаговые диалоги жили в in-memory словарях (`_constructor_sessions`,
`_fantasy_pending`, `_photo_offer_pending`, `_photo_offer_expression`,
`_custom_drafts`, `_pending_adult_photo`). Каждый редиплой на Railway
обнулял их: пользователь, оплативший конструктор персонажа или фэнтези,
терял незавершённый сценарий.

## Что сделано
- **`models/app_models.py`** — новая модель `DialogSession`
  (таблица `dialog_sessions`: telegram_id + session_key unique,
  payload_json, created_at/updated_at).
- **`services/dialog_store.py`** (новый) — фасад `DialogStore`,
  совместимый с обычным `dict[int, ...]`: `store[uid]`, `.get()`, `.pop()`,
  `del`, `in`. Каждый `__setitem__` сразу пишется в БД; значения-словари
  возвращаются как `_PersistentDict` (write-through на каждый ключ).
  Кодеки: базовый JSON с переносом `bytes` через base64 (фото лица в
  конструкторе) и отдельный кодек `photo_request` для `PhotoRequest`.
  Guard `MAX_PAYLOAD_CHARS` (~4 МБ) — слишком большие сессии остаются
  только в памяти и логируются.
- **`services/db.py`** — `DialogSession` добавлен в импорт, чтобы
  `create_all()` создал таблицу.
- **`main.py`**:
  - шесть пользовательских словарей заменены инстансами `DialogStore`
    (сигнатуры всех 40+ сайтов использования не менялись);
  - две in-place мутации переписаны в read/modify/write-back
    (`cons['params'][key] = value` и `_custom_drafts.setdefault(...)['color']`),
    иначе write-through их бы терял;
  - на старте `cleanup_stale_sessions()` удаляет сессии старше 24 часов.

## Что сознательно НЕ персистится
Админские редакторы (`_character_card_edit_sessions`,
`_payment_method_edit_sessions`, `_photo_idea_edit_sessions`,
`_library_import_sessions`) — ими пользуется один человек, перезапуск
тривиален.

## Граничные случаи
- Фэнтези хранит кортеж `(charge, amount)` как JSON-список — распаковка
  `charge, amount = ...` работает без изменений.
- Если фото лица в конструкторе превышает лимит, персистится сессия без
  байтов: после рестарта аватар рисуется полностью в AI-стиле (без
  face-swap), платёж не теряется.

## Проверка
- `tests/test_v3290_dialog_sessions_static.py` — 13 тестов
  (7 статических пинов + 6 рантайм на одноразовой sqlite с подменой
  `SessionLocal`).
- Полный прогон: 403 теста зелёные.

## Следующий шаг масштабирования
Шаг 3: очередь генераций — воркер, который разбирает `background_jobs`
со `status='queued'` по приоритету (уже есть в схеме с v3.28.0).
