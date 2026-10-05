from sqlalchemy import select, func
from services.db import SessionLocal
from services.user_service import ensure_user
from models.photo_models import PhotoLibraryPack, PhotoLibraryItem, UserSeenPhotoItem, UserSeenPhotoPack, PhotoDelivery
from models.app_models import UserGeneration
from services import dialog_store
from config import GALLERY_SET_SIZE

# V3.53.0: «Собери галерею» rolling set announcements. Keyed by telegram_id,
# value is {character_id: announced_sets_done}. Lives in the existing
# dialog_sessions table, so it is redeploy-safe and needs no schema change.
_gallery_sets = dialog_store.DialogStore('gallery_sets')


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


# ── V3.53.0 «Собери галерею» — rolling photo-set counter ─────────────────────
# For one character, every photo the user has actually received counts toward a
# set of GALLERY_SET_SIZE (default 50). Reaching a multiple completes one gallery
# set («quest done»), then the next set begins. Two DISJOINT sources are summed:
# the bot writes PhotoDelivery but never UserGeneration, and the Mini App writes
# UserGeneration but never PhotoDelivery — so nothing is double counted.

_APP_PHOTO_KINDS = ('photo', 'circle', 'video', 'hot', 'cosplay')


def collected_photo_count(telegram_id: int, character_id: str) -> int:
    """How many photos of this character the user has received (bot + app)."""
    try:
        uid = ensure_user(telegram_id)
        tg = int(telegram_id)
        with SessionLocal() as s:
            bot_n = s.scalar(
                select(func.count(PhotoDelivery.id)).where(
                    PhotoDelivery.user_id == uid,
                    PhotoDelivery.character_id == character_id,
                )
            ) or 0
            app_n = s.scalar(
                select(func.count(UserGeneration.id)).where(
                    UserGeneration.telegram_id == tg,
                    UserGeneration.character_id == character_id,
                    UserGeneration.kind.in_(_APP_PHOTO_KINDS),
                )
            ) or 0
        return int(bot_n) + int(app_n)
    except Exception:
        return 0


def gallery_set_progress(telegram_id: int, character_id: str) -> dict:
    """The rolling «N из 50» gallery-set progress for one character."""
    per = max(1, int(GALLERY_SET_SIZE))
    count = collected_photo_count(telegram_id, character_id)
    sets_done = count // per
    progress = count % per
    return {
        'count': count,
        'per_set': per,
        'sets_done': sets_done,
        'progress': progress,
        'remaining': per - progress,
        'complete': progress == 0 and count > 0,
    }


def note_gallery_set(telegram_id: int, character_id: str) -> int:
    """Return how many gallery sets were newly completed since we last announced
    this character, and stamp the announced count. Fail-silent (0)."""
    try:
        tg = int(telegram_id)
        sets_done = gallery_set_progress(telegram_id, character_id)['sets_done']
        current = dict(_gallery_sets.get(tg) or {})
        prior_n = int(current.get(str(character_id), 0) or 0)
        if sets_done > prior_n:
            current[str(character_id)] = sets_done
            _gallery_sets[tg] = current
            return sets_done - prior_n
        if str(character_id) not in current:
            # First sight: stamp without celebrating so an existing historical
            # collection does not instantly fire a stale 'quest done'.
            current[str(character_id)] = sets_done
            _gallery_sets[tg] = current
        return 0
    except Exception:
        return 0
