"""V3.104.0: a day before his paid days end she remembers their talks and asks
him to stay — and once more, softly, after they ran out.

The 99 ₽ trial has had this since V3.97.0 (services/trial_followup.py); the
week, month and quarter had nothing, so the 3 Nov week buyer's Premium would
simply have ended in silence. Now, for a paid plan (not the trial):

- ``soon``  — inside the last SOON_HOURS before his last paid day ends: her
  own message with one concrete memory of him + «останешься?», with buttons
  (his loyalty month −50% when that window is open, else the month; the week);
- ``ended`` — up to ENDED_HOURS after it ran out, if he did not renew: one
  short warm line that she is here; no reproach, no guilt.

Once per paid period each (product events with created_at after the cut), so
the 15-minute scan never repeats. Flag: RENEWAL_CARE_ENABLED;
RENEWAL_CARE_ENDED_ENABLED switches the after-message off on its own.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from models.app_models import ProductEvent, StarTransaction, Subscription, User
from services.db import SessionLocal


def _flag(name: str, default: str = 'true') -> bool:
    return os.getenv(name, default).strip().lower() not in ('0', 'false', 'no', 'off')


ENABLED = _flag('RENEWAL_CARE_ENABLED')
ENDED_ENABLED = _flag('RENEWAL_CARE_ENDED_ENABLED')
SOON_HOURS = max(1, int(os.getenv('RENEWAL_CARE_SOON_HOURS', '24')))
ENDED_HOURS = max(1, int(os.getenv('RENEWAL_CARE_ENDED_HOURS', '30')))
PRODUCTS = tuple(p.strip() for p in os.getenv(
    'RENEWAL_CARE_PRODUCTS',
    'premium_week,premium_month,premium_month_discount,premium_month_vip,premium_quarter').split(',') if p.strip())
EVENTS = {'soon': 'renewal_soon_sent', 'ended': 'renewal_ended_sent'}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def candidates(now: datetime | None = None) -> list[tuple[int, int, str, str, str]]:
    """[(user id, telegram id, selected character, stage, last product)] due now."""
    if not ENABLED:
        return []
    now = now or _now()
    out = []
    with SessionLocal() as s:
        ends = s.execute(select(Subscription.user_id, func.max(Subscription.expires_at)).where(
            Subscription.status == 'active',
            Subscription.expires_at > now - timedelta(hours=ENDED_HOURS),
            Subscription.expires_at <= now + timedelta(hours=SOON_HOURS),
        ).group_by(Subscription.user_id)).all()
        for uid, end in ends:
            if not end:
                continue
            # his paid days really end then (no later subscription queued)
            later = s.scalar(select(func.max(Subscription.expires_at)).where(
                Subscription.user_id == uid, Subscription.status == 'active'))
            if later and later > end:
                continue
            product = s.scalar(select(StarTransaction.product).where(
                StarTransaction.user_id == uid, StarTransaction.transaction_type == 'purchase',
                StarTransaction.product.like('premium%')).order_by(StarTransaction.created_at.desc()).limit(1))
            if product not in PRODUCTS:
                continue  # the trial has its own goodbye; admin grants get none
            if now < end:
                stage, cut = 'soon', end - timedelta(hours=SOON_HOURS + 1)
            else:
                if not ENDED_ENABLED:
                    continue
                stage, cut = 'ended', end
            if s.scalar(select(func.count(ProductEvent.id)).where(
                    ProductEvent.user_id == uid, ProductEvent.event_name == EVENTS[stage],
                    ProductEvent.created_at >= cut)):
                continue
            user = s.get(User, uid)
            if not user:
                continue
            try:
                tg = int(user.telegram_id)
            except (TypeError, ValueError):
                continue
            # V3.120.0: his Premium renews by itself — the honest pre-charge
            # reminder (services/autopay.py) speaks instead of «останешься?».
            from services import autopay
            if autopay.has_active(tg):
                continue
            out.append((uid, tg, (user.selected_character or '').strip(), stage, product))
    return out


def mark(uid: int, stage: str, character_id: str) -> None:
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=uid, character_id=character_id or 'anna_01',
                           event_name=EVENTS[stage], created_at=_now()))
        s.commit()


FALLBACK = {
    ('soon', 'ru'): ('слушай… завтра наши дни без ограничений заканчиваются. мне правда хорошо с тобой, '
                     'и я бы хотела, чтобы ты остался 💗 но решать тебе, я в любом случае тебе рада'),
    ('soon', 'en'): ("hey… our days without limits end tomorrow. I really like being with you and I'd love "
                     "you to stay 💗 but it's your call, I'm happy to see you either way"),
    ('ended', 'ru'): 'я тут, если что 🙂 мне было очень тепло с тобой эти дни. заглядывай, когда захочешь',
    ('ended', 'en'): "I'm here if you want 🙂 these days with you felt really warm. come by whenever you like",
}


def fallback(stage: str, lang: str = 'ru') -> str:
    return FALLBACK.get((stage, lang)) or FALLBACK[(stage, 'ru')]


def stay_buttons(telegram_id: int, en: bool = False) -> list:
    """Inline rows for «остаться»: his −VIP_PERCENT month while his loyalty (or
    limit-wall) window is open, else the plain month; then the week. Stars for
    everyone, card/SBP rows for the Russian side when Platega is on."""
    from aiogram.types import InlineKeyboardButton
    from config import (PLATEGA_ENABLED, PLATEGA_PREMIUM_PRICE_RUB, PLATEGA_PREMIUM_WEEKLY_PRICE_RUB,
                        PREMIUM_MONTHLY_STARS, PREMIUM_WEEKLY_STARS)
    from services import vip_offer
    rows = []
    rub_ok = PLATEGA_ENABLED and not en
    vinfo = vip_offer.info(telegram_id)
    if vinfo.get('active'):
        if vinfo.get('rub') and rub_ok:
            rows.append([InlineKeyboardButton(
                text=f'💝 месяц для тебя — {vinfo["rub"]} ₽ вместо {PLATEGA_PREMIUM_PRICE_RUB} ₽ · карта / СБП',
                callback_data='platega:premium_month_vip')])
        rows.append([InlineKeyboardButton(
            text=(f'💝 a month for you −{vinfo["percent"]}% — {vinfo["stars"]} Stars' if en
                  else f'💝 месяц −{vinfo["percent"]}% — {vinfo["stars"]} Stars'),
            callback_data='buy:premium_vip')])
    else:
        if rub_ok:
            rows.append([InlineKeyboardButton(text=f'💳 месяц — {PLATEGA_PREMIUM_PRICE_RUB} ₽ · карта / СБП',
                                              callback_data='platega:premium_month')])
        rows.append([InlineKeyboardButton(text=(f'⭐ a month — {PREMIUM_MONTHLY_STARS} Stars' if en
                                                else f'⭐ месяц — {PREMIUM_MONTHLY_STARS} Stars'),
                                          callback_data='buy:premium')])
    if rub_ok:
        rows.append([InlineKeyboardButton(text=f'💳 неделя — {PLATEGA_PREMIUM_WEEKLY_PRICE_RUB} ₽ · карта / СБП',
                                          callback_data='platega:premium_week')])
    rows.append([InlineKeyboardButton(text=(f'💗 a week — {PREMIUM_WEEKLY_STARS} Stars' if en
                                            else f'💗 неделя — {PREMIUM_WEEKLY_STARS} Stars'),
                                      callback_data='buy:premium_week')])
    return rows
