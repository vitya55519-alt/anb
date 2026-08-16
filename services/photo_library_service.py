from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections import defaultdict
import itertools

from sqlalchemy import and_, func, select

from models.photo_models import PhotoLibraryItem, PhotoLibraryPack, UserSeenPhotoPack
from services.collection_service import mark_items_seen
from services.db import SessionLocal
from services.user_service import ensure_user


@dataclass(frozen=True)
class LibraryPhoto:
    item_id: int
    file_id: str
    unique_id: str | None
    tier: str
    position: int
    video_file_id: str | None = None
    video_caption: str | None = None


@dataclass(frozen=True)
class LibraryPack:
    id: int
    character_id: str
    scene: str
    relationship_level: int
    pack_kind: str
    pack_key: str
    photos: tuple[LibraryPhoto, ...]


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _next_pack_number(session, character_id: str, scene: str, level: int) -> int:
    prefix = f'{character_id}_{scene}_L{level}_'
    keys = session.scalars(select(PhotoLibraryPack.pack_key).where(
        PhotoLibraryPack.character_id == character_id,
        PhotoLibraryPack.scene == scene,
        PhotoLibraryPack.relationship_level == level,
        PhotoLibraryPack.pack_key.like(prefix + '%'),
    )).all()
    best = 0
    for key in keys:
        try:
            best = max(best, int(str(key).rsplit('_', 1)[1]))
        except Exception:
            continue
    return best + 1


def import_buffered_photos(
    character_id: str,
    scene: str,
    relationship_level: int,
    mode: str,
    photos: list[dict],
) -> dict:
    """Persist Telegram file_ids collected by the admin importer.

    V3.11 keeps progression triples where possible, but never discards the tail.
    This makes a 10-photo level exactly 10 photos: 3+3+3+1.
    """
    relationship_level = max(1, min(6, int(relationship_level)))
    mode = 'progression' if mode == 'progression' else 'collection'
    groups: list[list[dict]] = []
    if mode == 'progression':
        full = (len(photos) // 3) * 3
        for i in range(0, full, 3):
            groups.append(photos[i:i+3])
        for i in range(full, len(photos)):
            groups.append([photos[i]])
    else:
        groups = [[p] for p in photos]

    created_ids: list[int] = []
    with SessionLocal() as session:
        number = _next_pack_number(session, character_id, scene, relationship_level)
        for group in groups:
            key = f'{character_id}_{scene}_L{relationship_level}_{number:03d}'
            pack_kind = 'progression' if len(group) == 3 else 'collection'
            pack = PhotoLibraryPack(
                character_id=character_id, scene=scene, relationship_level=relationship_level,
                pack_kind=pack_kind, pack_key=key, active=True,
            )
            session.add(pack); session.flush()
            tiers = ('base', 'stylish', 'premium') if len(group) == 3 else ('single',)
            for pos, (photo, tier) in enumerate(zip(group, tiers), start=1):
                session.add(PhotoLibraryItem(
                    pack_id=pack.id, position=pos, tier=tier,
                    telegram_file_id=photo['file_id'],
                    telegram_file_unique_id=photo.get('unique_id'),
                    source_caption=photo.get('caption'),
                    linked_video_file_id=photo.get('video_file_id'),
                    linked_video_unique_id=photo.get('video_unique_id'),
                    linked_video_caption=photo.get('video_caption'),
                ))
            created_ids.append(pack.id); number += 1
        session.commit()
    return {
        'packs_created': len(created_ids),
        'photos_saved': len(photos),
        'videos_saved': sum(1 for p in photos if p.get('video_file_id')),
        'tail_unsaved': 0,
    }


def regroup_collection_packs(character_id: str, scene: str, relationship_level: int) -> dict:
    """Convert existing one-photo collection packs into progression packs of three.

    This is an admin migration helper for V3.9.1 libraries. It does not re-upload
    images: existing Telegram file_ids are copied into new 3-frame packs. Any
    remainder of one or two photos is left untouched as collection packs.
    """
    relationship_level = max(1, min(6, int(relationship_level)))
    with SessionLocal() as session:
        packs = session.scalars(
            select(PhotoLibraryPack)
            .where(
                PhotoLibraryPack.character_id == character_id,
                PhotoLibraryPack.scene == scene,
                PhotoLibraryPack.relationship_level == relationship_level,
                PhotoLibraryPack.pack_kind == 'collection',
                PhotoLibraryPack.active.is_(True),
            )
            .order_by(PhotoLibraryPack.created_at.asc(), PhotoLibraryPack.id.asc())
        ).all()

        singles = []
        for pack in packs:
            items = session.scalars(
                select(PhotoLibraryItem)
                .where(PhotoLibraryItem.pack_id == pack.id)
                .order_by(PhotoLibraryItem.position.asc())
            ).all()
            if len(items) == 1:
                singles.append((pack, items[0]))

        usable = (len(singles) // 3) * 3
        if usable == 0:
            return {
                'packs_created': 0,
                'photos_regrouped': 0,
                'leftover_single_photos': len(singles),
            }

        next_number = _next_pack_number(session, character_id, scene, relationship_level)
        created = 0
        regrouped = 0
        tiers = ('base', 'stylish', 'premium')

        for offset in range(0, usable, 3):
            trio = singles[offset:offset + 3]
            key = f'{character_id}_{scene}_L{relationship_level}_{next_number:03d}'
            new_pack = PhotoLibraryPack(
                character_id=character_id,
                scene=scene,
                relationship_level=relationship_level,
                pack_kind='progression',
                pack_key=key,
                active=True,
            )
            session.add(new_pack)
            session.flush()

            old_pack_ids = [old_pack.id for old_pack, _item in trio]
            seen_rows = session.scalars(
                select(UserSeenPhotoPack).where(UserSeenPhotoPack.pack_id.in_(old_pack_ids))
            ).all()
            seen_by_user = {}
            for row in seen_rows:
                agg = seen_by_user.setdefault(row.user_id, {
                    'first_seen_at': row.first_seen_at,
                    'times_seen': 0,
                })
                if row.first_seen_at < agg['first_seen_at']:
                    agg['first_seen_at'] = row.first_seen_at
                agg['times_seen'] += row.times_seen

            for position, ((_old_pack, item), tier) in enumerate(zip(trio, tiers), start=1):
                session.add(PhotoLibraryItem(
                    pack_id=new_pack.id,
                    position=position,
                    tier=tier,
                    telegram_file_id=item.telegram_file_id,
                    telegram_file_unique_id=item.telegram_file_unique_id,
                    source_caption=item.source_caption,
                    linked_video_file_id=item.linked_video_file_id,
                    linked_video_unique_id=item.linked_video_unique_id,
                    linked_video_caption=item.linked_video_caption,
                ))

            for user_id, agg in seen_by_user.items():
                session.add(UserSeenPhotoPack(
                    user_id=user_id,
                    pack_id=new_pack.id,
                    first_seen_at=agg['first_seen_at'],
                    times_seen=max(1, agg['times_seen']),
                ))

            for row in seen_rows:
                session.delete(row)
            for old_pack, item in trio:
                session.delete(item)
                session.delete(old_pack)

            created += 1
            regrouped += 3
            next_number += 1

        session.commit()
        return {
            'packs_created': created,
            'photos_regrouped': regrouped,
            'leftover_single_photos': len(singles) - usable,
        }


def _pack_from_row(session, row: PhotoLibraryPack) -> LibraryPack:
    items = session.scalars(
        select(PhotoLibraryItem)
        .where(PhotoLibraryItem.pack_id == row.id)
        .order_by(PhotoLibraryItem.position.asc())
    ).all()
    return LibraryPack(
        id=row.id,
        character_id=row.character_id,
        scene=row.scene,
        relationship_level=row.relationship_level,
        pack_kind=row.pack_kind,
        pack_key=row.pack_key,
        photos=tuple(LibraryPhoto(
            i.id, i.telegram_file_id, i.telegram_file_unique_id, i.tier, i.position,
            i.linked_video_file_id, i.linked_video_caption,
        ) for i in items),
    )


def choose_unseen_pack(telegram_id: int, character_id: str, scene: str, relationship_level: int) -> LibraryPack | None:
    """Choose the closest eligible unseen pack. Higher matching levels are preferred.

    If all eligible packs were seen, reuse the least-seen/oldest pack instead of failing.
    """
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        eligible = session.scalars(
            select(PhotoLibraryPack)
            .where(
                PhotoLibraryPack.character_id == character_id,
                PhotoLibraryPack.scene == scene,
                PhotoLibraryPack.relationship_level <= relationship_level,
                PhotoLibraryPack.active.is_(True),
            )
            .order_by(PhotoLibraryPack.relationship_level.desc(), PhotoLibraryPack.id.asc())
        ).all()
        if not eligible:
            return None

        seen_rows = session.scalars(select(UserSeenPhotoPack).where(UserSeenPhotoPack.user_id == uid)).all()
        seen = {r.pack_id: r for r in seen_rows}
        unseen = [p for p in eligible if p.id not in seen]
        chosen = unseen[0] if unseen else min(
            eligible,
            key=lambda p: (seen.get(p.id).times_seen if seen.get(p.id) else 0, seen.get(p.id).first_seen_at if seen.get(p.id) else _now(), p.id),
        )
        return _pack_from_row(session, chosen)



def choose_fallback_pack(
    telegram_id: int,
    character_id: str,
    relationship_level: int,
    scene_order: tuple[str, ...] | list[str] | None = None,
) -> LibraryPack | None:
    """Choose an eligible library pack for graceful AI failure fallback.

    Unlike choose_unseen_pack(), this helper may search across several compatible
    scenes.  The caller provides scenes in preference order.  Unseen content is
    always preferred; once everything has been seen, the least-seen/oldest pack
    is reused instead of returning None.
    """
    uid = ensure_user(telegram_id)
    relationship_level = max(1, min(6, int(relationship_level)))
    preferred = tuple(dict.fromkeys(scene_order or ()))
    rank = {scene: idx for idx, scene in enumerate(preferred)}

    with SessionLocal() as session:
        query = select(PhotoLibraryPack).where(
            PhotoLibraryPack.character_id == character_id,
            PhotoLibraryPack.relationship_level <= relationship_level,
            PhotoLibraryPack.active.is_(True),
        )
        if preferred:
            query = query.where(PhotoLibraryPack.scene.in_(preferred))
        eligible = list(session.scalars(query).all())
        if not eligible:
            return None

        seen_rows = session.scalars(select(UserSeenPhotoPack).where(UserSeenPhotoPack.user_id == uid)).all()
        seen = {r.pack_id: r for r in seen_rows}

        def preference_key(pack: PhotoLibraryPack):
            return (
                rank.get(pack.scene, len(rank) + 1),
                -int(pack.relationship_level),
                int(pack.id),
            )

        unseen = [pack for pack in eligible if pack.id not in seen]
        if unseen:
            chosen = min(unseen, key=preference_key)
        else:
            chosen = min(
                eligible,
                key=lambda pack: (
                    rank.get(pack.scene, len(rank) + 1),
                    seen.get(pack.id).times_seen if seen.get(pack.id) else 0,
                    seen.get(pack.id).first_seen_at if seen.get(pack.id) else _now(),
                    -int(pack.relationship_level),
                    int(pack.id),
                ),
            )
        return _pack_from_row(session, chosen)

def mark_pack_seen(telegram_id: int, pack_id: int):
    uid = ensure_user(telegram_id)
    item_ids = []
    with SessionLocal() as session:
        row = session.scalar(select(UserSeenPhotoPack).where(
            UserSeenPhotoPack.user_id == uid,
            UserSeenPhotoPack.pack_id == pack_id,
        ))
        if row:
            row.times_seen += 1
        else:
            session.add(UserSeenPhotoPack(user_id=uid, pack_id=pack_id, first_seen_at=_now(), times_seen=1))
        item_ids = list(session.scalars(select(PhotoLibraryItem.id).where(PhotoLibraryItem.pack_id == pack_id)).all())
        session.commit()
    mark_items_seen(telegram_id, item_ids)



@dataclass(frozen=True)
class LinkedLibraryVideo:
    item_id: int
    video_file_id: str
    caption: str | None
    scene: str
    relationship_level: int


def get_linked_video(item_id: int, character_id: str, relationship_level: int) -> LinkedLibraryVideo | None:
    """Return an owner-uploaded video only when its photo is currently accessible."""
    relationship_level = max(1, min(6, int(relationship_level)))
    with SessionLocal() as session:
        row = session.execute(
            select(PhotoLibraryItem, PhotoLibraryPack)
            .join(PhotoLibraryPack, PhotoLibraryItem.pack_id == PhotoLibraryPack.id)
            .where(
                PhotoLibraryItem.id == int(item_id),
                PhotoLibraryPack.character_id == character_id,
                PhotoLibraryPack.relationship_level <= relationship_level,
                PhotoLibraryPack.active.is_(True),
            )
        ).first()
        if not row:
            return None
        item, pack = row
        if not item.linked_video_file_id:
            return None
        return LinkedLibraryVideo(
            item_id=item.id,
            video_file_id=item.linked_video_file_id,
            caption=item.linked_video_caption,
            scene=pack.scene,
            relationship_level=pack.relationship_level,
        )

def library_stats(character_id: str | None = None) -> dict:
    with SessionLocal() as session:
        q = select(PhotoLibraryPack).where(PhotoLibraryPack.active.is_(True))
        if character_id:
            q = q.where(PhotoLibraryPack.character_id == character_id)
        packs = session.scalars(q).all()
        by_scene: dict[tuple[str, str, int], dict] = defaultdict(lambda: {'packs': 0, 'photos': 0, 'videos': 0})
        total_photos = 0
        total_videos = 0
        for p in packs:
            n = session.scalar(select(func.count(PhotoLibraryItem.id)).where(PhotoLibraryItem.pack_id == p.id)) or 0
            videos = session.scalar(select(func.count(PhotoLibraryItem.id)).where(
                PhotoLibraryItem.pack_id == p.id,
                PhotoLibraryItem.linked_video_file_id.is_not(None),
            )) or 0
            key = (p.character_id, p.scene, p.relationship_level)
            by_scene[key]['packs'] += 1
            by_scene[key]['photos'] += int(n)
            by_scene[key]['videos'] += int(videos)
            total_photos += int(n)
            total_videos += int(videos)
        return {
            'total_packs': len(packs),
            'total_photos': total_photos,
            'total_videos': total_videos,
            'by_scene': dict(by_scene),
        }


def delete_pack(pack_id: int) -> bool:
    with SessionLocal() as session:
        pack = session.get(PhotoLibraryPack, pack_id)
        if not pack:
            return False
        session.delete(pack)
        session.commit()
        return True
