from sqlalchemy import select
from services.db import SessionLocal
from services.relationship_engine import RelationshipDelta, apply_delta, build_relationship_context, get_state
from models.relationship_models import UserCharacterRelationship
from models.app_models import User
from config import CHARACTER_ID

async def record_user_message(user_id, user_name, relationship=0, trust=0, intimacy=0, event_type="interaction", reason=""):
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(user_id)))
        if not user:
            user = User(telegram_id=str(user_id), name=user_name)
            s.add(user); s.flush()
        else:
            user.name = user_name
        row = apply_delta(s, user.id, CHARACTER_ID, RelationshipDelta(
            relationship=relationship, trust=trust, intimacy=intimacy,
            event_type=event_type, reason=reason
        ))
        return build_relationship_context(row)

async def get_context(user_id, character_id=CHARACTER_ID):
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(user_id)))
        if not user:
            return None
        row = get_state(s, user.id, character_id)
        return build_relationship_context(row)
