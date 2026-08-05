from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from config import CHARACTER_ID, DAILY_IMAGE_BUDGET_USD, MONTHLY_IMAGE_BUDGET_USD
from models.app_models import ProductEvent, StarTransaction, User, Message
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


def _retention_rate(day: int) -> float:
    """Simple closed-beta cohort retention: user sent a message in the 24h window starting at day N."""
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
            hit = s.scalar(select(func.count(ProductEvent.id)).where(ProductEvent.user_id == u.id, ProductEvent.event_name == 'chat_user_message', ProductEvent.created_at >= start, ProductEvent.created_at < end)) or 0
            if hit:
                retained += 1
    return retained / len(users) * 100.0


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
    }
