from datetime import datetime, timezone
from sqlalchemy import select, delete
from services.db import SessionLocal
from services.user_service import ensure_user
from models.app_models import UserConsent, User, Message, Memory, CommunicationProfile, CharacterState, Reminder, Subscription, StarTransaction, ProductEvent, CustomCharacter
from models.photo_models import PhotoDailyUsage, PhotoDelivery, PhotoOffer, UserSeenPhotoPack, UserSeenPhotoItem
from models.relationship_models import UserCharacterRelationship, RelationshipEvent, RelationshipMilestone
from models.quest_models import UserQuestProgress, QuestReplayOffer

TERMS_VERSION = '2026-08-14'
PRIVACY_VERSION = '2026-08-14'


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def has_accepted(telegram_id: int) -> bool:
    uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        row = s.scalar(select(UserConsent).where(UserConsent.user_id == uid))
        return bool(row and row.accepted and row.terms_version == TERMS_VERSION and row.privacy_version == PRIVACY_VERSION)


def accept(telegram_id: int):
    uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        row = s.scalar(select(UserConsent).where(UserConsent.user_id == uid))
        if not row:
            row = UserConsent(user_id=uid)
            s.add(row)
        row.terms_version = TERMS_VERSION
        row.privacy_version = PRIVACY_VERSION
        row.accepted = True
        row.accepted_at = _now()
        s.commit()


def delete_user_data(telegram_id: int) -> bool:
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.telegram_id == str(telegram_id)))
        if not user:
            return False
        uid = user.id
        rel_ids = list(s.scalars(select(UserCharacterRelationship.id).where(UserCharacterRelationship.user_id == uid)).all())
        if rel_ids:
            s.execute(delete(RelationshipEvent).where(RelationshipEvent.user_character_id.in_(rel_ids)))
            s.execute(delete(RelationshipMilestone).where(RelationshipMilestone.user_character_id.in_(rel_ids)))
        for model in (QuestReplayOffer, UserQuestProgress, UserSeenPhotoItem, UserSeenPhotoPack, PhotoDailyUsage, PhotoDelivery, PhotoOffer,
                      ProductEvent, StarTransaction, Subscription, Reminder, CharacterState, CommunicationProfile, Memory, Message,
                      UserConsent, UserCharacterRelationship):
            s.execute(delete(model).where(model.user_id == uid))
        # V3.19.0: constructor characters are keyed by telegram_id directly.
        s.execute(delete(CustomCharacter).where(CustomCharacter.telegram_id == str(telegram_id)))
        s.delete(user)
        s.commit()
        return True
