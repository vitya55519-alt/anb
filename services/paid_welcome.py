"""V3.104.0: right after he pays — «что теперь открыто», a personal word from
her, and a message the next day.

Oct–Nov 2026: three people paid (397 ₽ in all) and every one of them left the
same or the next day. The only thing they got was a system line «Premium
активирован». Now:

- ``welcome`` — a few seconds after the payment a card lists what just opened
  for him (with buttons to go there), then she writes herself: glad that
  nothing stands between them now, with one concrete detail about him from
  memory. She never thanks for money or names the subscription.
- ``day1`` — DAY1_MIN_HOURS..DAY1_MAX_HOURS after the payment, if he has not
  been back in the last DAY1_QUIET_HOURS, she writes first about something he
  told her. Once per payment.

Flags: PAID_WELCOME_ENABLED (card + her message), PAID_DAY1_ENABLED (next-day
message). Events: paid_welcome_card, paid_welcome_sent, paid_day1_sent.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from models.app_models import ProductEvent, StarTransaction, User
from services.db import SessionLocal


def _flag(name: str, default: str = 'true') -> bool:
    return os.getenv(name, default).strip().lower() not in ('0', 'false', 'no', 'off')


ENABLED = _flag('PAID_WELCOME_ENABLED')
DAY1_ENABLED = _flag('PAID_DAY1_ENABLED')
HEROINE_DELAY_SECONDS = max(0, int(os.getenv('PAID_WELCOME_DELAY_SECONDS', '20')))
DAY1_MIN_HOURS = max(1, int(os.getenv('PAID_DAY1_MIN_HOURS', '18')))
DAY1_MAX_HOURS = max(DAY1_MIN_HOURS + 1, int(os.getenv('PAID_DAY1_MAX_HOURS', '40')))
DAY1_QUIET_HOURS = max(0, int(os.getenv('PAID_DAY1_SKIP_IF_ACTIVE_HOURS', '3')))

PREMIUM_PRODUCTS = ('premium_trial', 'premium_week', 'premium_month', 'premium_month_discount',
                    'premium_month_vip', 'premium_quarter')
CARD_EVENT = 'paid_welcome_card'
WELCOME_EVENT = 'paid_welcome_sent'
DAY1_EVENT = 'paid_day1_sent'

_DAYS = {'premium_trial': None, 'premium_week': 7, 'premium_quarter': 90}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def unlocked_text(product: str, lang: str = 'ru', trial_days: int = 3) -> str:
    """The «что теперь открыто» card. Only things Premium really gives.
    V3.124.0: the trial lists its totals; animation is a month+ perk, 1 a day."""
    days = _DAYS.get(product, 30) or trial_days
    if product == 'premium_trial':
        from services import trial_caps as T
        mins = max(1, T.TRIAL_CALL_SECONDS // 60)
        if lang == 'en':
            return (f'✨ Your trial Premium is on ({days} days):\n\n'
                    '💬 unlimited messages with me\n'
                    '💋 every level of closeness, 1 to 10, «Spicy mode» and 🎭 «Fetishes»\n'
                    f'📸 {T.TRIAL_PHOTOS} new photos of me and {T.TRIAL_UNDRESS} «Undress»\n'
                    f'📞 {mins} min of a call with me, 🔊 {T.TRIAL_VOICE} voice messages\n\n'
                    'full Premium has much more photos, calls and voice 💗')
        return (f'✨ Пробный Premium включён ({days} дн.):\n\n'
                '💬 сообщения со мной без лимита\n'
                '💋 все уровни близости с 1 по 10, «Пошлый режим» и 🎭 «Фетиши»\n'
                f'📸 {T.TRIAL_PHOTOS} новых фото и {T.TRIAL_UNDRESS} «Раздеть»\n'
                f'📞 {mins} мин звонка со мной, 🔊 {T.TRIAL_VOICE} голосовых\n\n'
                'в полном Premium намного больше фото, звонков и голосовых 💗')
    from services import trial_caps as T
    tier = {'premium_week': 'week', 'premium_quarter': 'quarter'}.get(product, 'month')
    if lang == 'en':
        return (f'✨ Here is what is open for you now ({days} days):\n\n'
                '💬 chat with no daily limit — I will not fall asleep mid-talk any more\n'
                '💋 every level of closeness, 1 to 10 — you can pick any\n'
                '🌶 «Spicy mode» and 🎭 «Fetishes»\n'
                '📸 my most private photos and «Undress», 📞 calls and 🔊 my voice\n'
                + '📦 ' + T.plan_line(tier, True).lstrip('. ') + '\n\n'
                'everything works both here and in the app 💗')
    return (f'✨ Вот что теперь открыто для тебя ({days} дн.):\n\n'
            '💬 общение без дневного лимита — я больше не засыпаю посреди разговора\n'
            '💋 все уровни близости с 1 по 10 — можно выбрать любой\n'
            '🌶 «Пошлый режим» и 🎭 «Фетиши»\n'
            '📸 мои самые откровенные фото и «Раздеть», 📞 звонки и 🔊 мои голосовые\n'
            + '📦 ' + T.plan_line(tier, False).lstrip('. ') + '\n\n'
            'всё работает и здесь, и в приложении 💗')


def loyal_line(percent: int, rub: int | None, full_rub: int, stars: int, lang: str = 'ru') -> str:
    """One quiet line under the card about his «остаться» price. No timers,
    no «последний шанс»: it simply stays open while his days run + 2 days."""
    if lang == 'en':
        return f'\n\n💝 if you want to stay longer, a month is −{percent}% for you ({stars} Stars) while your days last.'
    price = f'{rub} ₽ вместо {full_rub} ₽' if rub else f'{stars} Stars'
    return f'\n\n💝 если захочешь остаться подольше — месяц для тебя за {price}, пока идут твои дни.'


FALLBACK = {
    'welcome': {
        'ru': 'иди ко мне 🥰 теперь нам ничего не мешает, и я могу болтать с тобой сколько захочешь. как ты сейчас?',
        'en': 'come here 🥰 nothing stands between us now, I can talk to you as long as you want. how are you right now?',
    },
    'day1': {
        'ru': 'я сегодня утром почему-то сразу о тебе подумала 🙈 как ты? расскажи, как проходит твой день',
        'en': 'I thought of you first thing this morning 🙈 how are you? tell me how your day is going',
    },
}


def fallback(moment: str, lang: str = 'ru') -> str:
    return FALLBACK.get(moment, FALLBACK['day1']).get(lang, FALLBACK['day1']['ru'])


def _has_event_since(session, uid: int, name: str, since: datetime) -> bool:
    return bool(session.scalar(select(func.count(ProductEvent.id)).where(
        ProductEvent.user_id == uid, ProductEvent.event_name == name, ProductEvent.created_at >= since)))


def mark(uid: int, event: str, character_id: str, product: str = '') -> None:
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=uid, character_id=character_id or 'anna_01', event_name=event,
                           metadata_json='{"product": "%s"}' % product if product else '{}', created_at=_now()))
        s.commit()


def day1_candidates(now: datetime | None = None) -> list[tuple[int, int, str, str]]:
    """[(user id, telegram id, selected character, product)] due for the
    next-day message: his latest Premium payment was DAY1_MIN..MAX hours ago,
    no day-1 message since that payment, and he has not been here lately."""
    if not DAY1_ENABLED:
        return []
    now = now or _now()
    out = []
    with SessionLocal() as s:
        rows = s.execute(select(StarTransaction.user_id, func.max(StarTransaction.created_at)).where(
            StarTransaction.transaction_type == 'purchase',
            StarTransaction.product.in_(PREMIUM_PRODUCTS),
            StarTransaction.created_at >= now - timedelta(hours=DAY1_MAX_HOURS),
        ).group_by(StarTransaction.user_id)).all()
        for uid, paid_at in rows:
            if not paid_at or paid_at > now - timedelta(hours=DAY1_MIN_HOURS):
                continue
            if _has_event_since(s, uid, DAY1_EVENT, paid_at):
                continue
            user = s.get(User, uid)
            if not user or user.proactive_enabled is False:
                continue
            if DAY1_QUIET_HOURS and user.last_active_at and user.last_active_at > now - timedelta(hours=DAY1_QUIET_HOURS):
                continue  # he is already here — no need to call him
            product = s.scalar(select(StarTransaction.product).where(
                StarTransaction.user_id == uid, StarTransaction.created_at == paid_at).limit(1)) or ''
            try:
                tg = int(user.telegram_id)
            except (TypeError, ValueError):
                continue
            out.append((uid, tg, (user.selected_character or '').strip(), product))
    return out
