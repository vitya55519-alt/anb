# V3.30.1 — логи в stdout, тишина в консоли Railway

## Проблема (логи владельца)

Каждая строка лога в консоли Railway помечена `"severity":"error"`, хотя сами
сообщения — INFO («задание _reminders выполнено successfully», «обработано
обновление»). Ошибок в них нет.

## Причина

- Python `logging` по умолчанию пишет в **stderr**, а Railway считает stderr
  ошибочным потоком и taggingует severity=error всё, что туда попало.
- Дополнительно консоль засоряли INFO-тики `apscheduler.executors.default`
  каждые 30 секунд и `aiogram.event` на каждый апдейт.

## Fix

- `main.py`: `logging.basicConfig(..., stream=sys.stdout)` — весь лог идёт в
  stdout, INFO остаётся INFO в консоли Railway.
- `apscheduler` и `aiogram.event` переведены на WARNING: тики напоминаний и
  per-update строки больше не flood'ят лог; предупреждения и ошибки видны.
- Русский перевод имён логгеров в консоли («исполнители.по умолчанию») —
  фича авто-перевода Railway, отключается в настройках просмотра логов.

## Тесты

- `tests/test_v3301_log_stdout_static.py` — пины stdout-stream и silenced
  логгеров; версионные пины расширены до 3.30.1.
