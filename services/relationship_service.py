from sqlalchemy import select
from services.db import SessionLocal
from services.relationship_engine import RelationshipDelta, apply_delta, build_relationship_context, get_state, get_milestones
from models.relationship_models import UserCharacterRelationship
from models.app_models import User
from config import CHARACTER_ID
from services.analytics_service import track_event

async def record_user_message(user_id, user_name, relationship=0, trust=0, intimacy=0, event_type="interaction", reason=""):
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(user_id)))
        if not user:
            user = User(telegram_id=str(user_id), name=user_name)
            s.add(user); s.flush()
        else:
            user.name = user_name
        existing = s.scalar(select(UserCharacterRelationship).where(
            UserCharacterRelationship.user_id == user.id,
            UserCharacterRelationship.character_id == CHARACTER_ID,
        ))
        old_stage = existing.stage if existing else 'stranger'
        row = apply_delta(s, user.id, CHARACTER_ID, RelationshipDelta(
            relationship=relationship, trust=trust, intimacy=intimacy,
            event_type=event_type, reason=reason
        ))
        context = build_relationship_context(row, get_milestones(s, row))
        if row.stage != old_stage:
            track_event(user.id, 'relationship_level_up', metadata={'from': old_stage, 'to': row.stage})
            context += ' Отношения только что перешли на новый этап: пусть в этой или ближайшей реплике это слегка чувствуется через большее узнавание, тепло или уверенность, но не называй номер уровня и не объявляй системное событие.'
        return context

async def get_context(user_id, character_id=CHARACTER_ID):
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(user_id)))
        if not user:
            return None
        row = get_state(s, user.id, character_id)
        return build_relationship_context(row, get_milestones(s, row))
