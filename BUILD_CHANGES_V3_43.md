# BUILD CHANGES V3.43.0 — «Come Closer catch-up»: поддержка-бот, бонус за канал, платёжное меню

## 1. Поддержка уехала в отдельного бота
- Все кнопки «👥 Поддержка» (welcome-ряд и reply-кнопка меню) теперь дают
  url-кнопку `https://t.me/Anna67901support_bot` — пользователи пишут команде
  прямо там; username берётся из env `SUPPORT_BOT_USERNAME`
  (default `Anna67901support_bot`), токен саппорт-бота в репозиторий НЕ попадает.
- Мёртвый callback `support:open` удалён; `/support`-тикеты оставлены только
  для админ-потока.

## 2. +100 🍑 за подписку на канал (@Anna634212)
- Конфиг: `CHANNEL_SUBSCRIBE_USERNAME` (default `Anna634212`),
  `CHANNEL_SUBSCRIBE_BONUS_CREDITS` (default 100).
- Вкладка «Персонажи»: баннер «Бесплатные 🍑 за подписку на канал» → подарочная
  модалка («В канал», «Проверить подписку», предупреждение
  «При отписке бонус аннулируется»).
- `POST /webapp/api/channel_bonus`: `get_chat_member` (member/administrator/
  creator) → одноразовый `grant_photo_credits`; при отписке —
  `revoke_photo_credits` (маркер снимается, персики вычитаются не ниже нуля).
- В payments.py новые helpers `has_credit_grant` / `revoke_photo_credits`.

## 3. Авторизация Mini App больше не «отваливается»
- `WEBAPP_INIT_DATA_MAX_AGE` (default 604800 = 7 дней) вместо 24 часов —
  клиенты, открывающие приложение из «недавних», больше не получают 401.
- `_webapp_api_me` логирует причину отказа (missing / expired / hash).
- Фронтенд вместо голой ошибки показывает WHY + кнопку «Открыть заново»
  (`authErrHtml()`): отдельные тексты для «открыто вне Telegram» и
  «устаревшие данные входа».

## 4. Тарифная карта как у конкурента + квартальный план
- Три тира: неделя / месяц / 3 месяца с рублёвыми ценами 299 / 899 / 1799 ₽
  (env `FREEKASSA_PREMIUM_WEEKLY_PRICE_RUB` / `FREEKASSA_PREMIUM_PRICE_RUB` /
  `FREEKASSA_PREMIUM_QUARTERLY_PRICE_RUB`), бейдж выгоды и зачёркнутая цена
  «если покупать по неделе».
- Квартальный продукт end-to-end: `PREMIUM_QUARTERLY_STARS` (1200) /
  `PREMIUM_QUARTERLY_PHOTO_CREDITS` (36), `premium_quarter` в PRODUCTS,
  грант 90 дней, callback `buy:premium_quarter`, FreeKassa-цена в
  `_fk_amount_for`, подтверждение в notify-цепочке.

## 5. Витрина: карусель, лайк, лайтбокс
- Страница персонажа: карусель фото со стрелками и точками (Come Closer style)
  + кнопка-сердце «лайк» (`CharacterLike` с составным PK + `CharacterStat.likes`,
  `GET/POST /webapp/api/char_like`).
- Тап по фото в чате приложения открывает полноэкранный лайтбокс
  (глобальный делегат `img[data-lb]`).
- Галерея персонажей читает референсы `00_`…`05_` — у emily и maria появились
  дополнительные ракурсы, витрина больше не повторяет один кадр.

## 6. Платёжное меню «тап по квадрату → способы оплаты»
- Магазин перерисован в пак-квадраты (Stars-цена + ₽ + «Получить»); тап по
  квадрату открывает центрированную модалку `#paymodal` с рядами:
  ⭐ Telegram Stars · 🏦 СБП / карта · 💎 Крипта (TON/USDT).
- Ряд СБП показывается только при `FREEKASSA_ENABLED`, крипта — при
  `WALLET_PAY_ENABLED` (флаги приехали в payload `/webapp/api/shop`).
- `POST /webapp/api/pay_link`: СБП → FreeKassa REST-заказ с `i=42`
  (fallback SCI-форма), крипта → Wallet Pay invoice; ссылка открывается через
  `tg.openTelegramLink` / `tg.openLink`.
- Рублёвые заказы фото-кредита и квартального плана корректно грантятся в
  notify-цепочке (`product == 'photo'`, `premium_quarter`).

## 7. Надёжность установки кнопки «Открыть приложение»
- `set_chat_menu_button` с 3 попытками (backoff 3·attempt) + read-back
  `get_chat_menu_button` и лог результата.

## 8. Внешность героинь (канон v5/v6)
- Пересобраны канонические референсы всех 8 героинь в одобренном эталоне
  (emily v3): кукольное лицо, крылатые стрелки, glossy-губы, объёмная грудь,
  осиная талия, круглая подтянутая попа; одетый гламур без нюды.
- Эрика v6 — естественные орехово-зелёные глаза; Мила v6 — сексуальнее
  (сонный взгляд, бордовый шёлк), янтарные глаза без артефакта свечения.
- Файлы лежат в `data/references/<name>/00_*_face.png` + `01_*_look.png` и
  автоматически становятся каноном для всех будущих генераций
  (photo_service подставляет их как image-референсы + PHOTO IDENTITY-замок).

## Tests / version
- Новый `tests/test_v3430_release_static.py` (10 тестов: саппорт-бот, бонус за
  канал, auth-hardening, квартал, retry меню, карусель/лайк/лайтбокс, галерея,
  платёжное меню).
- Обновлены stale-тесты: test_v3390 (ref_hint), test_v3314/test_v3421
  (url-кнопка саппорта), test_v3380 (ticket-flow), test_v3340 (whitelist
  шаблонов + пак-квадраты), test_v3341 (грант-блок с кварталом).
- VERSION → 3.43.0, пины версий обновлены в 34 тестовых файлах.
