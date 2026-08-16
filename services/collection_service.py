from sqlalchemy import select, func
from services.db import SessionLocal
from services.user_service import ensure_user
from models.photo_models import PhotoLibraryPack, PhotoLibraryItem, UserSeenPhotoItem, UserSeenPhotoPack


def mark_items_seen(telegram_id: int, item_ids: list[int]):
    if not item_ids: return
    uid = ensure_user(telegram_id)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        for item_id in item_ids:
            row = s.scalar(select(UserSeenPhotoItem).where(UserSeenPhotoItem.user_id == uid, UserSeenPhotoItem.photo_item_id == item_id))
            if row:
                row.times_seen += 1; row.last_seen_at = now
            else:
                s.add(UserSeenPhotoItem(user_id=uid, photo_item_id=item_id, first_seen_at=now, last_seen_at=now, times_seen=1))
        s.commit()



def _backfill_from_seen_packs(uid: int):
    """Preserve collection progress for users from pre-V3.11 pack-level tracking."""
    from datetime import datetime, timezone
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as s:
        existing=set(s.scalars(select(UserSeenPhotoItem.photo_item_id).where(UserSeenPhotoItem.user_id==uid)).all())
        pack_rows=s.scalars(select(UserSeenPhotoPack).where(UserSeenPhotoPack.user_id==uid)).all()
        changed=False
        for seen_pack in pack_rows:
            item_ids=s.scalars(select(PhotoLibraryItem.id).where(PhotoLibraryItem.pack_id==seen_pack.pack_id)).all()
            for item_id in item_ids:
                if item_id not in existing:
                    s.add(UserSeenPhotoItem(user_id=uid,photo_item_id=item_id,first_seen_at=seen_pack.first_seen_at,last_seen_at=now,times_seen=max(1,seen_pack.times_seen)))
                    existing.add(item_id); changed=True
        if changed: s.commit()

def collection_progress(telegram_id: int, character_id: str, relationship_level: int) -> dict:
    uid = ensure_user(telegram_id)
    _backfill_from_seen_packs(uid)
    level = max(1, min(6, int(relationship_level)))
    per_level = []
    with SessionLocal() as s:
        accessible_ids = list(s.scalars(
            select(PhotoLibraryItem.id).join(PhotoLibraryPack, PhotoLibraryItem.pack_id == PhotoLibraryPack.id).where(
                PhotoLibraryPack.character_id == character_id,
                PhotoLibraryPack.relationship_level <= level,
                PhotoLibraryPack.active.is_(True),
            )
        ).all())
        seen_ids = set(s.scalars(select(UserSeenPhotoItem.photo_item_id).where(
            UserSeenPhotoItem.user_id == uid,
            UserSeenPhotoItem.photo_item_id.in_(accessible_ids) if accessible_ids else False,
        )).all()) if accessible_ids else set()
        for lv in range(1, 7):
            total = s.scalar(select(func.count(PhotoLibraryItem.id)).join(PhotoLibraryPack).where(
                PhotoLibraryPack.character_id == character_id,
                PhotoLibraryPack.relationship_level == lv,
                PhotoLibraryPack.active.is_(True),
            )) or 0
            ids = list(s.scalars(select(PhotoLibraryItem.id).join(PhotoLibraryPack).where(
                PhotoLibraryPack.character_id == character_id,
                PhotoLibraryPack.relationship_level == lv,
                PhotoLibraryPack.active.is_(True),
            )).all())
            seen = len(set(ids) & seen_ids) if lv <= level else 0
            per_level.append({'level': lv, 'total': int(total), 'seen': int(seen), 'unlocked': lv <= level})
    return {'seen': len(seen_ids), 'total': len(accessible_ids), 'per_level': per_level}
