# V3.55.8 — quest_claims: колонка varchar(64) ломала задания на Postgres

## Что показал Railway-лог (скриншот владельца)
V3.55.7 убрал ложный error-toast, а его логирование вскрыло настоящий корень:

```
psycopg.errors.StringDataRightTruncation: значение слишком длинное для типа
character varying(64)
[SQL: UPDATE users SET ... quest_claims=... ]
[parameters: {'quest_claims': '{"2026-10-04": ["dream","day","red","sweet"],
"2026-10-06": ["sweet"]}'}]
```

`users.quest_claims` (V3.49.0) хранила JSON-карту заявок за 5 дней в
`String(64)`. Ключей больше двух дней — и JSON переваливает за 64 символа;
Postgres отвергает UPDATE, `session.commit()` внутри `claim_quest` падает, и
каждое следующее засчитанное за день задание выдавало ошибку (на SQLite
длины не проверяются — локальные тесты это поймать не могут).

## Фикс
- `models/app_models.py`: `quest_claims` → `Text` (с комментарием).
- `services/db.py`: `_widen_quest_claims_column()` — явный
  `ALTER TABLE users ALTER COLUMN quest_claims TYPE TEXT` в `init_db()`
  (create_all и auto-migrate типы существующих колонок не меняют — прецедент
  `_drop_legacy_constructor_unique`). Fail-silent: на SQLite statement
  невалиден и длины не enforced, пропуск ожидаем.

Деплой сам расширит колонку при старте; битых данных не было — коммит
просто не проходил, карта заявок осталась в пределах старых значений.

## Тесты
- `tests/test_v3558_quest_claims_width_static.py` — 2 пина: модель = Text
  (и не String(64)); миграция определена, вызвана в init_db и fail-silent.
- Полный прогон: базлайн **16f/1037p/1e** (+2 новых теста к V3.55.7).

## VERSION
Не бампан; деплой только по слову «деплой».
