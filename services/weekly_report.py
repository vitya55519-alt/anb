"""V3.97.0: a weekly report to the owner in Telegram (Monday 09:00 MSK, /week).

Until now the numbers had to be dug out of a database backup by hand. The
report answers the owner's questions in one message: how many came, how many
stayed, who paid and how much, and how each recent feature is doing — the
free voice listens, the trial and the −50% month, the morning callback, the
first-minutes nudge, «Девушка дня» and Агата.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from models.app_models import Message, PlategaOrder, ProductEvent, StarTransaction, User
from services.db import SessionLocal


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _events(s, since, name: str) -> tuple[int, int]:
    row = s.execute(select(func.count(ProductEvent.id), func.count(func.distinct(ProductEvent.user_id))).where(
        ProductEvent.created_at >= since, ProductEvent.event_name == name)).one()
    return int(row[0] or 0), int(row[1] or 0)


def collect(days: int = 7) -> dict:
    now = _now()
    since = now - timedelta(days=days)
    out: dict = {'days': days}
    with SessionLocal() as s:
        new_ids = list(s.scalars(select(User.id).where(User.created_at >= since)).all())
        out['new'] = len(new_ids)
        out['active'] = int(s.scalar(select(func.count(User.id)).where(User.last_active_at >= since)) or 0)
        wrote = set()
        if new_ids:
            wrote = set(s.scalars(select(ProductEvent.user_id).where(
                ProductEvent.user_id.in_(new_ids),
                ProductEvent.event_name.in_(('chat_user_message', 'webapp_chat_message')))).all())
        out['new_wrote'] = len(wrote)
        out['messages'] = int(s.scalar(select(func.count(Message.id)).where(
            Message.created_at >= since, Message.role == 'user')) or 0)
        # money: Stars purchases and paid card/SBP orders
        out['stars'] = int(s.scalar(select(func.coalesce(func.sum(StarTransaction.stars), 0)).where(
            StarTransaction.created_at >= since, StarTransaction.transaction_type == 'purchase',
            StarTransaction.provider == 'stars')) or 0)
        rub = 0
        paid_orders = s.execute(select(PlategaOrder.amount, PlategaOrder.product).where(
            PlategaOrder.created_at >= since, PlategaOrder.status == 'paid')).all()
        for amount, product in paid_orders:
            if product == 'plategacheck':
                continue
            try:
                rub += int(float(amount))
            except (TypeError, ValueError):
                pass
        out['rub'] = rub
        out['payers'] = int(s.scalar(select(func.count(func.distinct(StarTransaction.user_id))).where(
            StarTransaction.created_at >= since, StarTransaction.transaction_type == 'purchase',
            StarTransaction.provider != 'manual')) or 0)
        by_product = s.execute(select(StarTransaction.product, func.count(StarTransaction.id)).where(
            StarTransaction.created_at >= since, StarTransaction.transaction_type == 'purchase',
            StarTransaction.provider != 'manual').group_by(StarTransaction.product)).all()
        out['by_product'] = sorted(((p, int(n)) for p, n in by_product), key=lambda x: -x[1])
        for key in ('speak_premium_wall', 'speak_free', 'chat_sleep_block', 'vip_offer_shown',
                    'trial_followup_sent', 'morning_callback_sent', 'first_minutes_nudge_sent',
                    'paywall_view', 'webapp_pay_link', 'referral_qualified', 'daily_mission_claimed',
                    'paid_welcome_sent', 'paid_day1_sent', 'renewal_care_sent', 'memory_gift_used'):
            out[key] = _events(s, since, key)
        out['girlday_msgs'] = int(s.scalar(select(func.count(ProductEvent.id)).where(
            ProductEvent.created_at >= since, ProductEvent.event_name == 'webapp_chat_message',
            ProductEvent.metadata_json.like('%"girlday": true%'))) or 0)
        top = s.execute(select(Message.character_id, func.count(Message.id),
                               func.count(func.distinct(Message.user_id))).where(
            Message.created_at >= since, Message.role == 'user').group_by(Message.character_id).order_by(
            func.count(Message.id).desc()).limit(6)).all()
        out['top'] = [(c, int(n), int(u)) for c, n, u in top]
        agata = s.execute(select(func.count(Message.id), func.count(func.distinct(Message.user_id))).where(
            Message.created_at >= since, Message.role == 'user', Message.character_id == 'agata_01')).one()
        out['agata'] = (int(agata[0] or 0), int(agata[1] or 0))
        src = s.execute(select(User.source_tag, func.count(User.id)).where(User.created_at >= since).group_by(
            User.source_tag).order_by(func.count(User.id).desc()).limit(6)).all()
        out['sources'] = [((t or 'без метки'), int(n)) for t, n in src]
    try:
        from services.analytics_service import _retention_rate
        out['d1'] = _retention_rate(1)
    except Exception:
        out['d1'] = None
    return out


def render(d: dict, name_of=lambda cid: cid) -> str:
    def ev(key):
        n, u = d.get(key, (0, 0))
        return f'{n} ({u} чел.)'
    lines = [
        f'📈 Неделя в боте (последние {d["days"]} дней)',
        '',
        f'👥 новых: {d["new"]}, из них написали девушке {d["new_wrote"]} · активных: {d["active"]}',
        f'💬 сообщений от людей: {d["messages"]}',
        f'🔁 D1 (30 дней): {d["d1"]:.0f}%' if d.get('d1') is not None else '🔁 D1: —',
        f'💰 оплаты: {d["rub"]} ₽ картой/СБП + {d["stars"]} ⭐ · платящих: {d["payers"]}',
    ]
    if d.get('by_product'):
        lines.append('   ' + ', '.join(f'{p} ×{n}' for p, n in d['by_product']))
    lines += [
        '',
        '🧪 как работают новинки:',
        f'· голос бесплатно: {ev("speak_free")} · стена голоса: {ev("speak_premium_wall")}',
        f'· «уснула» (лимит): {ev("chat_sleep_block")} · месяц −50% показан: {ev("vip_offer_shown")}',
        f'· открыли оплату: {ev("webapp_pay_link")} · видели предложение: {ev("paywall_view")}',
        f'· письмо о конце пробника: {ev("trial_followup_sent")}',
        f'· после оплаты: «что открыто» {ev("paid_welcome_sent")} · на след. день {ev("paid_day1_sent")}',
        f'· «останешься?» перед концом Premium: {ev("renewal_care_sent")}',
        f'· она сама вспомнила о нём: {ev("memory_gift_used")}',
        f'· утро про вчерашний разговор: {ev("morning_callback_sent")}',
        f'· дожим в первые минуты: {ev("first_minutes_nudge_sent")}',
        f'· Девушка дня: {d["girlday_msgs"]} сообщений в приложении',
        f'· Агата: {d["agata"][0]} сообщений ({d["agata"][1]} чел.)',
        f'· рефералы дошли до 10 сообщений: {ev("referral_qualified")} · миссии: {ev("daily_mission_claimed")}',
        '',
        '🏆 с кем говорят:',
    ]
    lines += [f'· {name_of(c)} — {n} сооб. ({u} чел.)' for c, n, u in d.get('top', [])] or ['· пусто']
    lines += ['', '📥 откуда пришли:']
    lines += [f'· {t} — {n}' for t, n in d.get('sources', [])] or ['· нет новых']
    return '\n'.join(lines)
