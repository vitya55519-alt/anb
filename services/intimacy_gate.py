"""V3.90.0: owner — «весь интим только с премиумом».

Explicit sexting (EXPLICIT_CHAT_RULE, the card girls' dirty manner) opens
only for an active Premium. Without it she still flirts, but stops at hints
when he heads into sex, and once a day his explicit message gets a quiet
«🔥 Откровенно — с Premium» offer under her reply (app chip / bot button).
"""
from __future__ import annotations

import re

# His message heads into sex (RU + EN). Only a trigger for the offer; her
# reply itself is shaped by the prompt rule.
SEXT_REQUEST = re.compile(
    r'(секс|трах|выеб|ебат|ебу\b|ебл|кончи|кончу|оргазм|минет|сосать|отсос|член|киск[аеу]|пизд|сиськ|'
    r'грудь|соски|голая|голенькая|разденься|раздевайся|сними\s+(трусики|лифчик|всё|все)|возбужд|мокрая|'
    r'хочу\s+тебя|займ[её]мся|в\s+постел|пошл|интим|sex|fuck|horny|naked|nude|boobs|pussy|cum\b|blowjob)',
    re.I,
)

NON_PREMIUM_LINE = (
    'ГРАНИЦА БЕЗ PREMIUM: он не на Premium, поэтому секстинга и откровенных подробностей нет — ни тел, '
    'ни действий в постели, ни описаний секса. Флиртуй, дразни, намекай, говори, что он тебя заводит, '
    'но когда он ведёт к сексу, остановись на интриге («остальное… только для самых близких 😏») и сама '
    'переведи в игривый флирт. Не читай мораль и не говори про подписки, правила или оплату.'
)

OFFER_EVENT = 'sext_offer'
OFFERS_PER_DAY = 1
OFFER_TEXT_RU = '🔥 Откровенная переписка и фото — только с Premium'
OFFER_TEXT_EN = '🔥 Explicit chat — with Premium'


def wants_sext(text: str) -> bool:
    return bool(text and SEXT_REQUEST.search(text))


def should_offer(telegram_id: int, character_id: str, text: str) -> bool:
    """True when his explicit message deserves today's Premium offer.
    Notes the offer so it is shown at most OFFERS_PER_DAY a day."""
    if not wants_sext(text):
        return False
    try:  # V3.91/3.92: Агата and «🔥 Девушка дня» are open to everyone — nothing to upsell
        from services import girl_of_day
        from services.chat_service import DIRTY_FROM_START
        if character_id in DIRTY_FROM_START or girl_of_day.is_open(character_id):
            return False
    except Exception:
        pass
    try:
        from config import ADMIN_TELEGRAM_IDS
        from services.access_service import is_premium
        from services.user_service import ensure_user, is_adult_confirmed
        from services.chat_photo_allowance import count_today, note_today
        if telegram_id in ADMIN_TELEGRAM_IDS or is_premium(telegram_id) or not is_adult_confirmed(telegram_id):
            return False
        uid = ensure_user(telegram_id)
        if count_today(uid, OFFER_EVENT) >= OFFERS_PER_DAY:
            return False
        note_today(uid, OFFER_EVENT, character_id)
        return True
    except Exception:
        return False
