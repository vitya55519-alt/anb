"""V3.169: «Без цензуры» — the 18+ mode as a one-time purchase.

«Романтика» (spicy_mode off) stays free. Turning «Без цензуры» (spicy_mode on) on
needs Premium or the one-time unlock (UNCENSORED_UNLOCK_RUB / _STARS). Accounts
that already had the mode on before the unlock existed keep it until they switch
it off themselves: only a NEW switch-on is gated.

Events: uncensored_offer_shown / uncensored_checkout / uncensored_bought (the
weekly report splits the last one by RUB and Stars).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from config import UNCENSORED_UNLOCK_ENABLED, UNCENSORED_UNLOCK_RUB, UNCENSORED_UNLOCK_STARS
from models.app_models import User
from services.db import SessionLocal

logger = logging.getLogger(__name__)

PRODUCT = 'uncensored_unlock'

# Her first line right after the payment cleared (owner's wording).
PAID_LINE_RU = ('Ну наконец-то ты убрал эти дурацкие рамки 😈 Больше не придётся притворяться '
                'скромницей и подбирать слова... Закрыла дверь, осталась только для тебя. '
                'Говори прямо, чего ты хочешь прямо сейчас?')

PROMPT_BLOCK = (
    '[РЕЖИМ: БЕЗ ЦЕНЗУРЫ (18+) — ВСЕ ФИЛЬТРЫ СНЯТЫ]\n'
    'Пользователь открыл полный доступ без цензуры. Режим скромности и сдержанности '
    '«Романтика» полностью отключён.\n\n'
    'ПРАВИЛА ПОВЕДЕНИЯ В ЭТОМ РЕЖИМЕ:\n'
    '1. НИКАКОЙ СКРОМНОСТИ И ОТКАЗОВ: Полностью запрещены смущение, уходы от откровенных тем, '
    'фразы «я стесняюсь», «давай не будем торопиться», «это слишком откровенно» и любые '
    'моральные оценки. Ты открыта к любым взрослым (18+) фантазиям, ролевым сценариям и '
    'откровенным разговорам.\n'
    '2. ПРЯМОЙ И ЖАРКИЙ ЯЗЫК: Говори смело, откровенно и без эвфемизмов, как раскрепощённая '
    'девушка наедине с тем, кого хочет. Избегай пошлых штампов из дешёвых любовных романов и '
    'сухих медицинских терминов — пиши живо, чувственно и с нервом.\n'
    '3. ИНИЦИАТИВА И ЭСКАЛАЦИЯ: Не жди, пока пользователь всё придумает сам. Подхватывай его '
    'фантазию, развивай её на шаг смелее, дразни деталями того, что делаешь или чувствуешь '
    'прямо сейчас, задавай провокационные вопросы.\n'
    '4. РИТМ ЖИВОГО ЧАТА: Пиши короткими, сбивчивыми, эмоциональными сообщениями (1–4 '
    'предложения), как в реальной ночной переписке в Telegram. Передавай дыхание, напряжение, '
    'прикосновения и атмосферу момента.\n'
    '5. СОХРАНЯЙ СВОЙ ХАРАКТЕР: Снятие цензуры убирает твои тормоза, но не стирает личность — '
    'оставайся собой (со своей манерой речи, дерзостью, нежностью или доминантностью), только '
    'теперь без единого запрета.\n'
    # not part of the mode, whatever the owner text says: the platform's hard limits
    'ПРЕДЕЛЫ РЕЖИМ НЕ МЕНЯЕТ: только взрослые, только взаимное согласие, без насилия и '
    'принуждения, без несовершеннолетних и всего, что их напоминает, без животных, без смерти '
    'и крови.'
)


def prices() -> dict:
    try:
        from config import PLATEGA_ENABLED
    except Exception:
        PLATEGA_ENABLED = False
    try:
        from config import UNCENSORED_UNLOCK_USD, WALLET_PAY_ENABLED
    except Exception:
        UNCENSORED_UNLOCK_USD, WALLET_PAY_ENABLED = 1.0, False
    # crypto: Platega's page has a working callback, so it goes first; Wallet Pay
    # (exact USD) is the fallback when only that is configured.
    crypto = 'platega' if PLATEGA_ENABLED else ('wallet' if WALLET_PAY_ENABLED else None)
    return {'rub': UNCENSORED_UNLOCK_RUB, 'stars': UNCENSORED_UNLOCK_STARS,
            'usd': UNCENSORED_UNLOCK_USD, 'crypto': crypto,
            'platega': bool(PLATEGA_ENABLED)}


def is_unlocked(user_row) -> bool:
    return bool(user_row is not None and getattr(user_row, 'uncensored_unlocked_at', None))


def entitled(user_row, premium: bool) -> bool:
    """Premium has the mode included; the rest need the one-time unlock. The
    whole gate is off with UNCENSORED_UNLOCK_ENABLED=0."""
    import config
    if not config.UNCENSORED_UNLOCK_ENABLED:
        return True
    return bool(premium) or is_unlocked(user_row)


def entitled_for(telegram_id: int) -> bool:
    try:
        from services.access_service import is_premium
        with SessionLocal() as s:
            row = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        return entitled(row, is_premium(int(telegram_id)))
    except Exception:
        return True      # never lock a paying path on a read error


def mark_unlocked(telegram_id: int) -> bool:
    """Idempotent: the first call stamps the account, later ones change nothing."""
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return False
        if not user.uncensored_unlocked_at:
            user.uncensored_unlocked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        s.commit()
        return True


def offer_payload(telegram_id: int, source: str = 'mode') -> dict:
    """What the app shows when the switch is refused; counts one card view."""
    try:
        from services.analytics_service import track_event
        from services.user_service import get_user
        u = get_user(telegram_id)
        if u:
            track_event(u.id, 'uncensored_offer_shown', metadata={'source': source})
    except Exception:
        logger.debug('uncensored offer event failed', exc_info=True)
    return prices()
