from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from config import CHARACTER_ID, DAILY_IMAGE_BUDGET_USD, MONTHLY_IMAGE_BUDGET_USD
from models.app_models import ProductEvent, StarTransaction, Subscription, User, Message
from models.photo_models import PhotoDelivery
from services.db import SessionLocal


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def track_event(user_id: int | None, event_name: str, *, value: float = 0.0, metadata: dict | None = None, character_id: str = CHARACTER_ID) -> None:
    """Best-effort product analytics. Never raise into user-facing flows."""
    try:
        with SessionLocal() as s:
            s.add(ProductEvent(
                user_id=user_id,
                character_id=character_id,
                event_name=str(event_name)[:64],
                value=float(value or 0.0),
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
            ))
            s.commit()
    except Exception:
        return


def image_spend_window() -> dict:
    now = _now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as s:
        daily = s.scalar(select(func.coalesce(func.sum(PhotoDelivery.estimated_cost_usd), 0.0)).where(PhotoDelivery.created_at >= day_start)) or 0.0
        monthly = s.scalar(select(func.coalesce(func.sum(PhotoDelivery.estimated_cost_usd), 0.0)).where(PhotoDelivery.created_at >= month_start)) or 0.0
    return {'daily_usd': float(daily), 'monthly_usd': float(monthly)}


def budget_allows_photo() -> tuple[bool, str]:
    spend = image_spend_window()
    if DAILY_IMAGE_BUDGET_USD > 0 and spend['daily_usd'] >= DAILY_IMAGE_BUDGET_USD:
        return False, 'daily_budget'
    if MONTHLY_IMAGE_BUDGET_USD > 0 and spend['monthly_usd'] >= MONTHLY_IMAGE_BUDGET_USD:
        return False, 'monthly_budget'
    return True, 'ok'


# V3.59.0: «came back» means ANY action the user started — not only a text
# typed in the bot chat. Most people live in the Mini App now (chat, dates,
# stories, studio), and the old bot-only rule reported D1 ≈ 1% for users who
# were in fact coming back every day. Pushes the bot itself sends are excluded.
ACTIVE_EVENTS = (
    'chat_user_message', 'webapp_opened', 'webapp_chat_message', 'webapp_chat_media',
    'webapp_date_delivered', 'quest_route_completed', 'quest_beat_completed',
    'daily_quest_claimed', 'gallery_opened', 'photo_requested', 'webapp_picture_generated',
    'webapp_studio_video_generated', 'apartment_action', 'proactive_replied', 'stars_purchase',
)


def _retention_rate(day: int) -> float:
    """Cohort retention: the user did something themselves in the 24h window starting at day N."""
    now = _now()
    window_start_age = day + 1
    cohort_since = now - timedelta(days=30)
    eligible_before = now - timedelta(days=window_start_age)
    with SessionLocal() as s:
        users = s.scalars(select(User).where(User.created_at >= cohort_since, User.created_at <= eligible_before)).all()
        if not users:
            return 0.0
        retained = 0
        for u in users:
            start = u.created_at + timedelta(days=day)
            end = start + timedelta(days=1)
            hit = s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.user_id == u.id, ProductEvent.event_name.in_(ACTIVE_EVENTS), ProductEvent.created_at >= start, ProductEvent.created_at < end)) or 0
            if hit:
                retained += 1
    return retained / len(users) * 100.0


def onboarding_funnel(days: int = 30) -> dict:
    """V3.59.0: where new users drop on day 0 — /start → 18+ consent → first own
    message (bot or app) → came back on day 1. Shares of everyone who pressed /start."""
    since = _now() - timedelta(days=days)
    with SessionLocal() as s:
        ids = [u for u in s.scalars(select(User.id).where(User.created_at >= since)).all()]
        if not ids:
            return {'started': 0, 'consent': 0, 'first_message': 0}

        def _reached(names) -> int:
            return s.scalar(select(func.count(func.distinct(ProductEvent.user_id))).where(
                ProductEvent.user_id.in_(ids), ProductEvent.event_name.in_(names))) or 0
        return {
            'started': len(ids),
            'consent': int(_reached(('consent_accepted',))),
            'first_message': int(_reached(('chat_user_message', 'webapp_chat_message'))),
        }


def admin_snapshot() -> dict:
    now = _now()
    d1 = now - timedelta(days=1)
    d7 = now - timedelta(days=7)
    d30 = now - timedelta(days=30)
    with SessionLocal() as s:
        users_total = s.scalar(select(func.count(User.id))) or 0
        users_24h = s.scalar(select(func.count(User.id)).where(User.last_active_at >= d1)) or 0
        users_7d = s.scalar(select(func.count(User.id)).where(User.last_active_at >= d7)) or 0
        new_7d = s.scalar(select(func.count(User.id)).where(User.created_at >= d7)) or 0
        messages_24h = s.scalar(select(func.count(Message.id)).where(Message.created_at >= d1, Message.role == 'user')) or 0
        photos_24h = s.scalar(select(func.count(PhotoDelivery.id)).where(PhotoDelivery.created_at >= d1)) or 0
        photo_cost_24h = s.scalar(select(func.coalesce(func.sum(PhotoDelivery.estimated_cost_usd), 0.0)).where(PhotoDelivery.created_at >= d1)) or 0.0
        photo_cost_30d = s.scalar(select(func.coalesce(func.sum(PhotoDelivery.estimated_cost_usd), 0.0)).where(PhotoDelivery.created_at >= d30)) or 0.0
        stars_30d = s.scalar(select(func.coalesce(func.sum(StarTransaction.stars), 0)).where(StarTransaction.created_at >= d30)) or 0
        failures_24h = s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.created_at >= d1, ProductEvent.event_name == 'photo_failed')) or 0
        partial_24h = s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.created_at >= d1, ProductEvent.event_name == 'photo_partial')) or 0
        photo_requests_24h = s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.created_at >= d1, ProductEvent.event_name == 'photo_requested')) or 0
        proactive_sent_7d = s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.created_at >= d7, ProductEvent.event_name == 'proactive_sent')) or 0
        proactive_replied_7d = s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.created_at >= d7, ProductEvent.event_name == 'proactive_replied')) or 0
        feedback_like_7d = s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.created_at >= d7, ProductEvent.event_name == 'photo_feedback_like')) or 0
        feedback_dislike_7d = s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.created_at >= d7, ProductEvent.event_name == 'photo_feedback_dislike')) or 0
        first_frame_avg = s.scalar(select(func.avg(ProductEvent.value)).where(ProductEvent.created_at >= d1, ProductEvent.event_name == 'photo_first_frame_ready')) or 0.0
        # V3.40.0: the owner asked for a real user-statistics screen in the
        # admin panel — signups, paying users, message volume, media mix and
        # the character leaderboard join the beta counters.
        new_24h = s.scalar(select(func.count(User.id)).where(User.created_at >= d1)) or 0
        premium_active = s.scalar(select(func.count(Subscription.id)).where(Subscription.status == 'active', Subscription.expires_at > now)) or 0
        messages_7d = s.scalar(select(func.count(Message.id)).where(Message.created_at >= d7, Message.role == 'user')) or 0
        circles_24h = s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.created_at >= d1, ProductEvent.event_name == 'circle_delivered')) or 0
        videos_24h = s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.created_at >= d1, ProductEvent.event_name.like('%_video_delivered'))) or 0
        top_rows = s.execute(
            select(Message.character_id, func.count(Message.id).label('cnt'))
            .where(Message.created_at >= d7, Message.role == 'user')
            .group_by(Message.character_id)
            .order_by(func.count(Message.id).desc())
            .limit(5)
        ).all()
        # V3.47.0: acquisition-source breakdown of new users over the last 30d,
        # so a $100 buy-in is measurable — how many installs each ?start=src_
        # tag produced (organic = empty tag). Empty share: tag groups per source.
        src_rows = s.execute(
            select(User.source_tag, func.count(User.id).label('cnt'))
            .where(User.created_at >= d30)
            .group_by(User.source_tag)
            .order_by(func.count(User.id).desc())
            .limit(20)
        ).all()
        src_rows_window = {}
        for key, since in (('sources_24h', d1), ('sources_7d', d7)):
            src_rows_window[key] = s.execute(
                select(User.source_tag, func.count(User.id).label('cnt'))
                .where(User.created_at >= since)
                .group_by(User.source_tag)
                .order_by(func.count(User.id).desc())
                .limit(12)
            ).all()
    failure_rate = (failures_24h / photo_requests_24h * 100.0) if photo_requests_24h else 0.0
    proactive_reply_rate = (proactive_replied_7d / proactive_sent_7d * 100.0) if proactive_sent_7d else 0.0
    return {
        'users_total': int(users_total), 'users_24h': int(users_24h), 'users_7d': int(users_7d), 'new_7d': int(new_7d),
        'messages_24h': int(messages_24h), 'photos_24h': int(photos_24h), 'photo_requests_24h': int(photo_requests_24h),
        'photo_failures_24h': int(failures_24h), 'photo_partial_24h': int(partial_24h), 'photo_failure_rate': failure_rate,
        'photo_cost_24h': float(photo_cost_24h), 'photo_cost_30d': float(photo_cost_30d), 'stars_30d': int(stars_30d),
        'first_frame_avg_seconds': float(first_frame_avg), 'd1_retention': _retention_rate(1), 'd3_retention': _retention_rate(3), 'd7_retention': _retention_rate(7),
        'proactive_sent_7d': int(proactive_sent_7d), 'proactive_replied_7d': int(proactive_replied_7d), 'proactive_reply_rate': proactive_reply_rate,
        'feedback_like_7d': int(feedback_like_7d), 'feedback_dislike_7d': int(feedback_dislike_7d),
        'new_24h': int(new_24h), 'premium_active': int(premium_active), 'messages_7d': int(messages_7d),
        'circles_24h': int(circles_24h), 'videos_24h': int(videos_24h),
        'top_characters': [[cid, int(cnt)] for cid, cnt in top_rows],
        'sources': [[(tag or 'organic'), int(cnt)] for tag, cnt in src_rows],
        'sources_24h': [[(tag or 'organic'), int(cnt)] for tag, cnt in src_rows_window['sources_24h']],
        'sources_7d': [[(tag or 'organic'), int(cnt)] for tag, cnt in src_rows_window['sources_7d']],
        'funnel': onboarding_funnel(),
    }
