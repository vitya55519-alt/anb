# V3.30.2 — оплата открывается: фикс платёжной страницы FreeKassa

## Проблема

Владелец сообщил «СТРАНИЦА ПЛАТЕЖА НЕ ЗАГРУЖАЕТСЯ». Три причины:

## 1. Домен SCI-формы мёртв → pay.fk.money

`pay.freekassa.ru` (старый SCI-хост) отдаёт TLS-timeout — страница
физически не открывается. Текущая SCI-форма живёт на `pay.fk.money`
(доки 1.5), туда и перенаправили fallback-ссылку.

## 2. Параметр `i` обязателен — теперь всегда отправляется

Доки `orders/create` (строка 331): `i` (integer) — **Required** —
Payment system ID. Таблица ID — раздел 1.8 «Список доступных валют»:
42=СБП, 44=СБП (API), 4=VISA RUB, 2=FK WALLET USD и т.д.

Старый код отправлял `i` только если `/currencies` что-то вернул. Если
запрос не прошёл (нет ключа/сети/валюты) — `i` не отправлялся → API
отклонял заказ (400) → падали на SCI → на мёртвый домен → «не грузится».

Новая цепочка резолва:
```
pay_id = payment_system or /currencies → or FK_CURRENCY_PAYMENT_IDS[CUR]
```
Статический fallback `FK_CURRENCY_PAYMENT_IDS`:
- RUB → 42 (СБП)
- USD → 2 (FK WALLET USD)
- EUR → 3 (FK WALLET EUR)
- UAH → 7 (VISA UAH)
- KZT → 41 (VISA/MasterCard KZT)

## 3. Диагностический маршрут /fkcheck

`GET /fkcheck` на Railway-домене: прощупывает env-флаги, server-ip,
`/currencies`, создаёт тестовый ордер и печатает `location` + SCI
fallback-ссылку. Владелец открывает в браузере и видит, что реально
возвращает API.

## Тесты

- `tests/test_v3302_fk_payment_fix_static.py` — пины: домен pay.fk.money,
  подпись с currency (1.5), статическая таблица FK_CURRENCY_PAYMENT_IDS,
  маршрут /fkcheck, API-first в legacy-хендлерах.
- Версионные кортежи v3201–v3261, v3300, v3301 расширены до '3.30.2'.
