import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from services.db import SessionLocal
from services.relationship_engine import RelationshipDelta, apply_delta, build_relationship_context, get_state, get_milestones
from models.relationship_models import UserCharacterRelationship
from models.app_models import User
from config import CHARACTER_ID
from services.analytics_service import track_event

# Level-up ceremony hook. main.py registers an async callback that announces
# the new stage to the user; registry keeps the engine free of bot imports.
# Signature: async def notifier(telegram_id, old_stage, new_stage, character_id)
_stage_change_notifier = None


def set_stage_change_notifier(fn):
    global _stage_change_notifier
    _stage_change_notifier = fn


async def record_user_message(user_id, user_name, relationship=0, trust=0, intimacy=0, event_type="interaction", reason="", character_id=CHARACTER_ID):
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(user_id)))
        if not user:
            user = User(telegram_id=str(user_id), name=user_name)
            s.add(user); s.flush()
        else:
            user.name = user_name
        existing = s.scalar(select(UserCharacterRelationship).where(
            UserCharacterRelationship.user_id == user.id,
            UserCharacterRelationship.character_id == character_id,
        ))
        old_stage = existing.stage if existing else 'stranger'
        # Returning after a real absence is a moment she should notice.
        reconnect_days = 0
        if existing and existing.last_distinct_day:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            gap = (now.date() - existing.last_distinct_day.date()).days
            if gap >= 3:
                reconnect_days = gap
        row = apply_delta(s, user.id, character_id, RelationshipDelta(
            relationship=relationship, trust=trust, intimacy=intimacy,
            event_type=event_type, reason=reason
        ))
        context = build_relationship_context(row, get_milestones(s, row))
        if reconnect_days:
            context += (
                f' Пользователь вернулся после {reconnect_days} дней тишины: можно тепло и естественно отметить, '
                'что ты заметила его отсутствие и рада возвращению, без системных формулировок и без упрёка.'
            )
        # V3.21.0: from level 3 she has a pet name for him — use it naturally.
        if user.pet_name:
            context += f' Ты ласково зовёшь его «{user.pet_name}» — иногда естественно используй это обращение.'
        if row.stage != old_stage:
            track_event(user.id, 'relationship_level_up', metadata={'from': old_stage, 'to': row.stage}, character_id=character_id)
            context += ' Отношения только что перешли на новый этап: пусть в этой или ближайшей реплике это слегка чувствуется через большее узнавание, тепло или уверенность, но не называй номер уровня и не объявляй системное событие.'
            if _stage_change_notifier:
                try:
                    asyncio.get_running_loop().create_task(
                        _stage_change_notifier(user_id, old_stage, row.stage, character_id)
                    )
                except Exception:
                    pass
        return context

async def get_context(user_id, character_id=CHARACTER_ID):
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(user_id)))
        if not user:
            return None
        row = get_state(s, user.id, character_id)
        return build_relationship_context(row, get_milestones(s, row))
