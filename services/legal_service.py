"""V3.32.0: full legal documents for the payment-partner / bank approval.

Platega (СБП НСПК) onboarding requires, permanently accessible from the bot:
1. Политика конфиденциальности — full document (adapted from the partner
   template, telegra.ph/Politika-konfidencialnosti-08-01-83);
2. Пользовательское соглашение — full document (adapted from
   telegra.ph/Polzovatelskoe-soglashenie-08-01-39);
3. Контакты поддержки — the in-bot ticket system (/support, /paysupport);
4. Актуальные цены и тарифы — rendered live from config, so env overrides
   are always reflected;
5. Кодовое слово «чекап» on the legal menu for the approval period.

The documents are provided in Russian (the governing language); English
users get a short notice instead. Telegram's 4096-char message limit is
handled by split_legal_text().

Per the partner's compliance note, the texts deliberately contain NO
personal/registration data (ИП, ООО, ИНН) — only the service identity.
"""
from __future__ import annotations

import os

from config import (
    FREE_MESSAGES_PER_DAY,
    FREE_PHOTOS_LEVEL_1_2,
    FREE_PHOTOS_LEVEL_3_6,
    PREMIUM_MONTHLY_STARS,
    PREMIUM_MONTHLY_PHOTO_CREDITS,
    PREMIUM_MONTHLY_QUEST_REPLAYS,
    PHOTO_COST_STARS,
    CHAT_PHOTO_OFFER_STARS,
    CUSTOM_PHOTO_COST_STARS,
    QUEST_REPLAY_STARS,
    VIDEO_COST_STARS,
    VIDEO_PREMIUM_FREE_DAILY,
    GALLERY_DOWNLOAD_STARS,
    CONSTRUCTOR_COST_STARS,
    CONSTRUCTOR_COST_RUB,
    FREEKASSA_PREMIUM_PRICE_RUB,
    FREEKASSA_ENABLED,
)
from services import gifts_service

LEGAL_VERSION = '2026-09-15'
LEGAL_DATE_RU = '15 сентября 2026 г.'
LEGAL_DATE_SHORT = '15.09.2026'
# The service identity shown in every document header (env-configurable so a
# renamed bot does not need a code change).
LEGAL_BOT_USERNAME = os.getenv('LEGAL_BOT_USERNAME', '@Anna67901_bot').strip()
SERVICE_NAME = f'телеграм-бот AnnaBot ({LEGAL_BOT_USERNAME})'

# Temporary verification word for the payment partner's compliance check.
# Remove after the cashier registration is done (see BUILD_CHANGES_V3_32.md).
LEGAL_CHECK_WORD = 'чекап'


PRIVACY_POLICY = (
    '🔐 Политика конфиденциальности\n\n'
    f'Редакция от {LEGAL_DATE_RU} · сервис — {SERVICE_NAME}\n\n'
    '1. Общие положения\n\n'
    '1.1. Настоящая Политика конфиденциальности (далее — «Политика») регулирует порядок обработки и защиты '
    f'информации, которую Пользователь передаёт при использовании сервиса {SERVICE_NAME} (далее — «Сервис»).'
    '\n'
    '1.2. Используя Сервис, Пользователь подтверждает своё согласие с условиями Политики. Если Пользователь '
    'не согласен с условиями — он обязан прекратить использование Сервиса.\n\n'
    '2. Сбор информации\n\n'
    '2.1. Сервис может собирать следующие типы данных:\n'
    '• идентификаторы аккаунта (Telegram ID, имя и @username профиля);\n'
    '• историю переписки с виртуальными персонажами и извлечённые из неё воспоминания;\n'
    '• настройки, прогресс отношений, историю фото, коллекций и квестов;\n'
    '• технические записи о покупках (дата, продукт, способ оплаты — без платёжных реквизитов).\n'
    '2.2. Сервис не требует от Пользователя предоставления паспортных данных, документов, фотографий '
    'или другой личной информации, кроме минимально необходимой для работы.\n'
    '2.3. Платёжные данные (номера карт и иные реквизиты) обрабатываются исключительно платёжными '
    'провайдерами (Telegram Payments, банковские и платёжные системы) и Сервисом не хранятся.\n\n'
    '3. Использование информации\n\n'
    '3.1. Сервис может использовать полученную информацию исключительно для:\n'
    '• обеспечения работы функционала (персонализация, память диалога, отношения);\n'
    '• связи с Пользователем (в том числе для уведомлений и поддержки);\n'
    '• анализа и улучшения работы Сервиса.\n\n'
    '4. Передача информации третьим лицам\n\n'
    '4.1. Администрация не передаёт полученные данные третьим лицам, за исключением случаев:\n'
    '• если это требуется по закону;\n'
    '• если это необходимо для исполнения обязательств перед Пользователем '
    '(например, при работе с платёжными системами);\n'
    '• если Пользователь сам дал на это согласие.\n\n'
    '5. Хранение и защита данных\n\n'
    '5.1. Данные хранятся в течение срока, необходимого для достижения целей обработки.\n'
    '5.2. Пользователь может в любой момент очистить историю общения и память командой /reset '
    'или удалить все свои данные целиком командой /delete_me.\n'
    '5.3. Администрация принимает разумные меры для защиты данных, но не гарантирует абсолютную '
    'безопасность информации при передаче через интернет.\n\n'
    '6. Отказ от ответственности\n\n'
    '6.1. Пользователь понимает и соглашается, что передача информации через интернет всегда '
    'сопряжена с рисками.\n'
    '6.2. Администрация не несёт ответственности за утрату, кражу или раскрытие данных, если это '
    'произошло по вине третьих лиц или самого Пользователя.\n\n'
    '7. Изменения в Политике\n\n'
    '7.1. Администрация вправе изменять условия Политики без предварительного уведомления.\n'
    '7.2. Продолжение использования Сервиса после внесения изменений означает согласие Пользователя '
    'с новой редакцией Политики. Актуальная редакция всегда доступна в боте по команде /privacy.\n\n'
    '8. Контакты\n\n'
    '8.1. По всем вопросам обработки данных Пользователь может обратиться в службу поддержки через '
    'форму в самом боте: команда /support.'
)


USER_AGREEMENT = (
    '📄 Пользовательское соглашение\n\n'
    f'Редакция от {LEGAL_DATE_RU} · сервис — {SERVICE_NAME}\n\n'
    '1. Общие положения\n\n'
    '1.1. Настоящее Пользовательское соглашение (далее — «Соглашение») регулирует порядок использования '
    f'онлайн-сервиса {SERVICE_NAME} (далее — «Сервис»), предоставляемого Администрацией.\n'
    '1.2. Сервис предназначен исключительно для пользователей 18+. Все виртуальные персонажи являются '
    'вымышленными совершеннолетними AI-персонажами, а не реальными людьми.\n'
    '1.3. Используя Сервис, включая запуск бота, подтверждение возраста, оплату услуг или получение '
    'доступа к материалам, Пользователь подтверждает, что полностью ознакомился с условиями настоящего '
    'Соглашения и принимает их в полном объёме.\n'
    '1.4. В случае несогласия с условиями Соглашения Пользователь обязан прекратить использование Сервиса.\n\n'
    '2. Характер услуг и цифровых товаров\n\n'
    '2.1. Сервис предоставляет цифровые товары и услуги нематериального характера: общение с вымышленными '
    'AI-персонажами, генерацию фотографий и видео, интерактивные истории и дополнительные функции.\n'
    '2.2. Все материалы, предоставляемые через Сервис, созданы с использованием технологий искусственного '
    'интеллекта; персонажи, их изображения и истории вымышлены.\n'
    '2.3. Результаты генерации могут быть неточными. Сервис не заменяет профессиональную медицинскую, '
    'юридическую, финансовую или психологическую помощь.\n'
    '2.4. Пользователь осознаёт, что ценность цифровых товаров и услуг Сервиса заключается в форме подачи, '
    'сопровождении, поддержке и обновлениях.\n\n'
    '3. Отказ от гарантий и ответственности\n\n'
    '3.1. Сервис предоставляется на условиях «AS IS» («как есть»).\n'
    '3.2. Администрация не гарантирует соответствие Сервиса ожиданиям Пользователя и бесперебойную и '
    'безошибочную работу Сервиса.\n'
    '3.3. Администрация не несёт ответственности за любые прямые или косвенные убытки, включая упущенную '
    'выгоду, действия или бездействие третьих лиц, временные технические сбои и ограничения доступа.\n'
    '3.4. Все решения об использовании Сервиса принимаются Пользователем самостоятельно и на его риск.\n\n'
    '4. Законность использования\n\n'
    '4.1. Сервис не предназначен для поощрения, организации или содействия противоправной деятельности, '
    'эксплуатации несовершеннолетних или нарушения прав третьих лиц.\n'
    '4.2. Пользователь обязуется использовать Сервис исключительно в рамках применимого законодательства '
    'и правил третьих сторон.\n'
    '4.3. Ответственность за законность использования материалов и услуг Сервиса полностью возлагается '
    'на Пользователя.\n\n'
    '5. Интеллектуальная собственность\n\n'
    '5.1. Все материалы, размещённые в Сервисе, охраняются законодательством об интеллектуальной собственности.\n'
    '5.2. Пользователю запрещается копировать, распространять, перепродавать, передавать третьим лицам или '
    'иным образом использовать материалы Сервиса без разрешения правообладателя.\n'
    '5.3. Нарушение прав интеллектуальной собственности может повлечь ограничение доступа к Сервису '
    'без компенсации.\n\n'
    '6. Ограничение доступа\n\n'
    '6.1. Администрация вправе приостановить или ограничить доступ Пользователя к Сервису в случае '
    'нарушения условий настоящего Соглашения, выявления злоупотреблений, требований законодательства '
    'или платёжных провайдеров.\n'
    '6.2. Ограничение доступа не освобождает Пользователя от обязательств, возникших ранее.\n\n'
    '7. Платежи и возвраты\n\n'
    '7.1. Оплата услуг и цифровых товаров производится на условиях, указанных в разделе «Цены и тарифы» '
    'в самом боте, по тарифам, актуальным на момент оплаты.\n'
    '7.2. В связи с нематериальным характером цифровых товаров и услуг возврат денежных средств после '
    'предоставления доступа не осуществляется, за исключением случаев, указанных ниже.\n'
    '7.3. Возврат средств возможен только если услуга не была оказана по технической вине Сервиса или '
    'доступ к цифровому товару фактически не был предоставлен.\n'
    '7.4. Для рассмотрения вопроса о возврате Пользователь обязан обратиться в службу поддержки в течение '
    '24 часов с момента оплаты: команда /paysupport.\n'
    '7.5. Решение о возврате принимается Администрацией индивидуально.\n'
    '7.6. Пользователь обязуется не инициировать возврат платежа (chargeback) через платёжные системы без '
    'предварительного обращения в службу поддержки Сервиса.\n\n'
    '8. Конфиденциальность\n\n'
    '8.1. Порядок обработки персональных данных описан в Политике конфиденциальности (команда /privacy).\n\n'
    '9. Изменение условий\n\n'
    '9.1. Администрация вправе вносить изменения в настоящее Соглашение.\n'
    '9.2. Актуальная версия Соглашения публикуется в Сервисе и всегда доступна по команде /terms.\n'
    '9.3. Продолжение использования Сервиса означает согласие Пользователя с обновлёнными условиями.\n\n'
    '10. Контактная информация\n\n'
    '10.1. По всем вопросам Пользователь может обратиться в службу поддержки через форму в самом боте: '
    'команда /support (общие вопросы) и /paysupport (вопросы оплаты).\n\n'
    'Используя Сервис (в том числе запуская бота и/или вводя команду /start), Пользователь подтверждает, '
    'что ознакомлен с настоящим Соглашением и принимает его условия в полном объёме.'
)


def tariffs_text(lang: str = 'ru') -> str:
    """Live price list rendered from config — always the актуальные тарифы."""
    gift_min = min(g.cost for g in gifts_service.GIFTS)
    gift_max = max(g.cost for g in gifts_service.GIFTS)
    gift_discount = round(gifts_service.DAILY_DISCOUNT * 100)
    rub_lines = FREEKASSA_ENABLED
    if lang == 'en':
        lines = [
            '💰 Prices & tariffs',
            '',
            f'Actual as of {LEGAL_DATE_SHORT} · every price is shown in the bot before payment',
            '',
            f'⭐ Premium — 30-day subscription: {PREMIUM_MONTHLY_STARS} Telegram Stars'
            + (f' or {FREEKASSA_PREMIUM_PRICE_RUB} ₽ by card/SBP' if rub_lines else ''),
            f'Includes: {PREMIUM_MONTHLY_PHOTO_CREDITS} photo credits/month, '
            f'{PREMIUM_MONTHLY_QUEST_REPLAYS} story replays, {VIDEO_PREMIUM_FREE_DAILY} free video '
            'animations per day, wider chat limits and all characters.',
            '',
            'Free tier:',
            f'• chat — {FREE_MESSAGES_PER_DAY} messages per day',
            f'• photos — {FREE_PHOTOS_LEVEL_1_2}/day (relationship levels 1–2), '
            f'{FREE_PHOTOS_LEVEL_3_6}/day (levels 3+)',
            '',
            '📸 Photos:',
            f'• new photo set after the free limit — {PHOTO_COST_STARS}⭐',
            f'• photo by your chat scenario — {CHAT_PHOTO_OFFER_STARS}⭐',
            f'• custom photo by your own description — {CUSTOM_PHOTO_COST_STARS}⭐',
            f'• full-resolution gallery download — {GALLERY_DOWNLOAD_STARS}⭐ per photo',
            '',
            '🎬 Video:',
            f'• photo animation (video or video circle) — {VIDEO_COST_STARS}⭐',
            f'• Premium: {VIDEO_PREMIUM_FREE_DAILY} free per day',
            '',
            '🎯 Stories & characters:',
            f'• alternative story branch — {QUEST_REPLAY_STARS}⭐',
            f'• create your own character — {CONSTRUCTOR_COST_STARS}⭐'
            + (f' or {CONSTRUCTOR_COST_RUB} ₽' if rub_lines else ''),
            '',
            f'🎁 Gifts: {gift_min}⭐ – {gift_max}⭐ · gift of the day −{gift_discount}%',
            '',
            '💖 Supporting the project is voluntary tips (CloudTips) and never affects access to features.',
            '',
            'Prices may change; the actual cost is always shown in the bot before payment.',
        ]
        return '\n'.join(lines)
    lines = [
        '💰 Цены и тарифы',
        '',
        f'Актуальны на {LEGAL_DATE_SHORT} · любая цена показывается в боте до оплаты',
        '',
        f'⭐ Premium — подписка на 30 дней: {PREMIUM_MONTHLY_STARS} Telegram Stars'
        + (f' или {FREEKASSA_PREMIUM_PRICE_RUB} ₽ (карта/СБП)' if rub_lines else ''),
        f'Входит: {PREMIUM_MONTHLY_PHOTO_CREDITS} фото-кредитов в месяц, '
        f'{PREMIUM_MONTHLY_QUEST_REPLAYS} перезапуска историй, {VIDEO_PREMIUM_FREE_DAILY} бесплатных '
        'видео-оживлений в день, расширенные лимиты общения и все персонажи.',
        '',
        'Бесплатный функционал:',
        f'• общение — {FREE_MESSAGES_PER_DAY} сообщений в день',
        f'• фото — {FREE_PHOTOS_LEVEL_1_2} в день (уровни отношений 1–2), '
        f'{FREE_PHOTOS_LEVEL_3_6} в день (уровни 3+)',
        '',
        '📸 Фото:',
        f'• новый сет фото после бесплатного лимита — {PHOTO_COST_STARS}⭐',
        f'• фото по сценарию из чата — {CHAT_PHOTO_OFFER_STARS}⭐',
        f'• кастомное фото по своему описанию — {CUSTOM_PHOTO_COST_STARS}⭐',
        f'• скачивание из галереи в полном разрешении — {GALLERY_DOWNLOAD_STARS}⭐ за фото',
        '',
        '🎬 Видео:',
        f'• оживление фото (видео или кружочек) — {VIDEO_COST_STARS}⭐',
        f'• Premium: {VIDEO_PREMIUM_FREE_DAILY} бесплатно в день',
        '',
        '🎯 Истории и персонажи:',
        f'• альтернативная ветка истории — {QUEST_REPLAY_STARS}⭐',
        f'• создание своего персонажа — {CONSTRUCTOR_COST_STARS}⭐'
        + (f' или {CONSTRUCTOR_COST_RUB} ₽' if rub_lines else ''),
        '',
        f'🎁 Подарки: от {gift_min}⭐ до {gift_max}⭐ · подарок дня −{gift_discount}%',
        '',
        '💖 Поддержка проекта — добровольные чаевые (CloudTips) и никак не влияют на доступ к функциям.',
        '',
        'Цены могут изменяться; актуальная стоимость всегда указана в боте перед оплатой.',
    ]
    return '\n'.join(lines)


def support_text(lang: str = 'ru') -> str:
    if lang == 'en':
        return (
            '🛟 Support\n\n'
            'Support works right inside the bot — every message goes directly to the project owner:\n'
            '• /support — general questions, bugs, suggestions\n'
            '• /paysupport — payment and refund issues (per the agreement — within 24 hours after payment)\n'
            '• /delete_me — full deletion of your data\n'
            '• /reset — clear chat history and memory\n\n'
            'We reply within a day. There is no Telegram group — only the bot’s own ticket form.'
        )
    return (
        '🛟 Поддержка\n\n'
        'Служба поддержки работает прямо в боте — каждое сообщение получает владелец проекта:\n'
        '• /support — общие вопросы, ошибки, предложения\n'
        '• /paysupport — вопросы оплаты и возвратов (по правилам соглашения — в течение 24 часов после платежа)\n'
        '• /delete_me — полное удаление ваших данных\n'
        '• /reset — очистка истории и памяти\n\n'
        'Отвечаем обычно в течение суток. Группа в Telegram не используется — только личная тикет-система бота.'
    )


def legal_menu_text(lang: str = 'ru') -> str:
    """Header of the always-available legal menu (buttons ride below it)."""
    if lang == 'en':
        return (
            '📜 Documents & prices\n\n'
            '• 🔐 Privacy policy\n'
            '• 📄 User agreement\n'
            '• 💰 Prices & tariffs\n'
            '• 🛟 Support\n\n'
            f'Tap a button below. Current revision: {LEGAL_DATE_SHORT}.\n\n'
            f'code word: {LEGAL_CHECK_WORD}'
        )
    return (
        '📜 Документы и цены\n\n'
        '• 🔐 Политика конфиденциальности\n'
        '• 📄 Пользовательское соглашение\n'
        '• 💰 Цены и тарифы\n'
        '• 🛟 Поддержка\n\n'
        f'Нажми кнопку ниже. Актуальные редакции: {LEGAL_DATE_SHORT}.\n\n'
        f'кодовое слово: {LEGAL_CHECK_WORD}'
    )


def legal_doc_notice(lang: str = 'ru') -> str:
    """Short notice above a Russian legal document for English users."""
    if lang == 'en':
        return 'The legal documents of the service are provided in Russian (the governing version).'
    return ''


def split_legal_text(text: str, limit: int = 3500) -> list[str]:
    """Split a long document into Telegram-sized messages.

    Splits on blank lines so sections stay intact; a pathological single
    paragraph longer than ``limit`` is hard-split.
    """
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in text.split('\n\n'):
        block = paragraph if not current else '\n\n' + paragraph
        if size + len(block) > limit and current:
            chunks.append('\n\n'.join(current))
            current, size = [], 0
            block = paragraph
        if len(block) > limit:
            if current:
                chunks.append('\n\n'.join(current))
                current, size = [], 0
            for i in range(0, len(block), limit):
                chunks.append(block[i:i + limit])
            continue
        current.append(paragraph)
        size += len(block)
    if current:
        chunks.append('\n\n'.join(current))
    return chunks
