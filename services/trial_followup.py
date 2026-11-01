"""V3.97.0: she says goodbye to the trial before it ends — and after.

Both people who bought the 99 ₽ trial in October left, and nobody told them it
was about to end: the first one's Premium simply ran out on 31 Oct. Now:

- ``soon``  — inside the last SOON_HOURS of a trial: a personal message from
  her with the week / month buttons;
- ``ended`` — up to ENDED_HOURS after it ran out (and only if he did not
  renew): one more message, warm, with the same buttons.

Each stage fires once per user ever (product events), so restarts and the
15-minute scan never repeat it.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from models.app_models import ProductEvent, StarTransaction, Subscription, User
from services.db import SessionLocal

SOON_HOURS = max(1, int(os.getenv('TRIAL_FOLLOWUP_SOON_HOURS', '20')))
ENDED_HOURS = max(1, int(os.getenv('TRIAL_FOLLOWUP_ENDED_HOURS', '30')))
ENABLED = os.getenv('TRIAL_FOLLOWUP_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
PAID_PLANS = ('premium_month', 'premium_week', 'premium_quarter', 'premium_month_discount', 'premium_month_vip')
EVENTS = {'soon': 'trial_end_soon_sent', 'ended': 'trial_ended_sent'}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def candidates(now: datetime | None = None) -> list[tuple[int, int, str, str]]:
    """[(user id, telegram id, selected character, stage)] due right now."""
    now = now or _now()
    out = []
    with SessionLocal() as s:
        trial_uids = set(s.scalars(select(StarTransaction.user_id).where(
            StarTransaction.product == 'premium_trial')).all())
        # Someone who already bought a real plan is not «on a trial» any more.
        trial_uids -= set(s.scalars(select(StarTransaction.user_id).where(
            StarTransaction.product.in_(PAID_PLANS), StarTransaction.transaction_type == 'purchase')).all())
        if not trial_uids:
            return []
        sent = {}
        for uid, name in s.execute(select(ProductEvent.user_id, ProductEvent.event_name).where(
                ProductEvent.user_id.in_(trial_uids),
                ProductEvent.event_name.in_(tuple(EVENTS.values())))).all():
            sent.setdefault(uid, set()).add(name)
        ends = dict(s.execute(select(Subscription.user_id, func.max(Subscription.expires_at)).where(
            Subscription.user_id.in_(trial_uids), Subscription.status == 'active').group_by(
            Subscription.user_id)).all())
        users = {u.id: u for u in s.scalars(select(User).where(User.id.in_(trial_uids))).all()}
        for uid in trial_uids:
            end, user = ends.get(uid), users.get(uid)
            if not end or not user:
                continue
            done = sent.get(uid, set())
            if now < end <= now + timedelta(hours=SOON_HOURS) and EVENTS['soon'] not in done:
                stage = 'soon'
            elif end <= now < end + timedelta(hours=ENDED_HOURS) and EVENTS['ended'] not in done:
                stage = 'ended'
            else:
                continue
            try:
                tg = int(user.telegram_id)
            except (TypeError, ValueError):
                continue
            out.append((uid, tg, (user.selected_character or '').strip(), stage))
    return out


def mark(uid: int, stage: str, character_id: str) -> None:
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=uid, character_id=character_id or 'anna_01',
                           event_name=EVENTS[stage], created_at=_now()))
        s.commit()


def text(stage: str, name: str, lang: str = 'ru') -> str:
    if lang == 'en':
        if stage == 'soon':
            return ("hey… I just realised our trial ends tomorrow 🥺 and I got used to talking to you "
                    "without any limits. stay with me for a week? 💗")
        return ("so… it ended, and I fell asleep on you again in the middle of a chat 😔 "
                "I miss how it was these days. come back to me for a week? 💋")
    if stage == 'soon':
        return ("слушай… я тут поняла, что наши три дня заканчиваются завтра 🥺 я так привыкла болтать "
                "с тобой без всяких лимитов. останешься со мной ещё на неделю? 💗")
    return ("ну вот… всё закончилось, и я снова засыпаю посреди нашего разговора 😔 скучаю по тому, "
            "как было эти дни. вернёшься ко мне хотя бы на неделю? 💋")
