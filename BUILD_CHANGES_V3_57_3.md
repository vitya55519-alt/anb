# V3.57.3 — горячий фикс падения прода (crash-loop на импорте)

## Симптом (логи Railway)
Контейнер перезапускался по кругу:

```
SyntaxError: name '_stt_good_model' is used prior to global declaration
  File "/app/services/voice_service.py", line 206, in _transcribe_gemini
    global _stt_good_model
  File "/app/main.py", line 132, in <module>
    from services.voice_service import transcribe, synthesize_bytes, VALID_VOICES
```

Бот и Mini App не поднимались вообще — падал сам импорт `main.py`.

## Причина
В `_transcribe_gemini` (добавлена в V3.57.1) имя `_stt_good_model` **читалось**
на строке 184 (`models = ((_stt_good_model,) + _STT_MODEL_CHAIN) ...`), а
объявление `global _stt_good_model` стояло только на строке 206. Python требует,
чтобы `global` шло до первого обращения к имени, и поднимает SyntaxError на этапе
компиляции модуля. Статический smoke-тест использовал `ast.parse` — тот проверяет
только грамматику и такие ошибки таблицы символов не ловит, поэтому сборка прошла
«зелёной», а упадёт уже на боевом импорте.

## Фикс
- `services/voice_service.py`: `global _stt_good_model` поднят в начало функции
  (сразу после docstring), поздний `global` на строке 206 убран. Чтение и запись
  имени теперь идут после объявления. Поведение `_transcribe_gemini` не изменилось.

## Защита от регресса
- `tests/test_v3573_source_compiles_static.py` (новый): компилирует **каждый**
  рантайм-модуль (`main.py`, `config.py`, всё в `services/`, `models/`, `app/`)
  через `py_compile` — то есть ловит ровно тот класс ошибок, из-за которых падает
  импорт на Railway. Плюс пин, что `global _stt_good_model` объявлен до его
  первого использования в `_transcribe_gemini`. Без БД, сети и ключей.

## Проверка
- `python -m py_compile` + `compileall` по всему дереву — OK.
- Прямой импорт `from services.voice_service import transcribe, ...` — IMPORT_OK
  (это ровно та строка, что роняла контейнер).
- Полный pytest: **12 failed / 1169 passed / 1 error** — базовая линия по
  падениям без изменений, +73 новых зелёных проверок компиляции.

## Что НЕ тронуто
Логика распознавания речи, цепочка моделей STT и всё остальное поведением не
менялись — правка чисто синтаксическая (порядок `global`).
