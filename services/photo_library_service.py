from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections import defaultdict
import itertools

from sqlalchemy import and_, func, select

from models.photo_models import PhotoLibraryItem, PhotoLibraryPack, UserSeenPhotoPack
from services.db import SessionLocal
from services.user_service import ensure_user


@dataclass(frozen=True)
class LibraryPhoto:
    file_id: str
    unique_id: str | None
    tier: str
    position: int


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

    mode=progression groups photos in upload order into 3-frame packs:
    base -> stylish -> premium. Incomplete tail is not saved.
    mode=collection saves each image as a one-photo pack.
    """
    relationship_level = max(1, min(6, int(relationship_level)))
    mode = 'progression' if mode == 'progression' else 'collection'
    groups = []
    if mode == 'progression':
        for i in range(0, len(photos) - (len(photos) % 3), 3):
            groups.append(photos[i:i+3])
    else:
        groups = [[p] for p in photos]

    created_ids: list[int] = []
    with SessionLocal() as session:
        number = _next_pack_number(session, character_id, scene, relationship_level)
        for group in groups:
            key = f'{character_id}_{scene}_L{relationship_level}_{number:03d}'
            pack = PhotoLibraryPack(
                character_id=character_id,
                scene=scene,
                relationship_level=relationship_level,
                pack_kind=mode,
                pack_key=key,
                active=True,
            )
            session.add(pack)
            session.flush()
            tiers = ('base', 'stylish', 'premium') if mode == 'progression' else ('single',)
            for pos, (photo, tier) in enumerate(zip(group, tiers), start=1):
                session.add(PhotoLibraryItem(
                    pack_id=pack.id,
                    position=pos,
                    tier=tier,
                    telegram_file_id=photo['file_id'],
                    telegram_file_unique_id=photo.get('unique_id'),
                    source_caption=photo.get('caption'),
                ))
            created_ids.append(pack.id)
            number += 1
        session.commit()
    return {
        'packs_created': len(created_ids),
        'photos_saved': sum(3 if mode == 'progression' else 1 for _ in created_ids),
        'tail_unsaved': len(photos) % 3 if mode == 'progression' else 0,
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
        photos=tuple(LibraryPhoto(i.telegram_file_id, i.telegram_file_unique_id, i.tier, i.position) for i in items),
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


def mark_pack_seen(telegram_id: int, pack_id: int):
    uid = ensure_user(telegram_id)
    with SessionLocal() as session:
        row = session.scalar(select(UserSeenPhotoPack).where(
            UserSeenPhotoPack.user_id == uid,
            UserSeenPhotoPack.pack_id == pack_id,
        ))
        if row:
            row.times_seen += 1
        else:
            session.add(UserSeenPhotoPack(user_id=uid, pack_id=pack_id, first_seen_at=_now(), times_seen=1))
        session.commit()


def library_stats(character_id: str | None = None) -> dict:
    with SessionLocal() as session:
        q = select(PhotoLibraryPack).where(PhotoLibraryPack.active.is_(True))
        if character_id:
            q = q.where(PhotoLibraryPack.character_id == character_id)
        packs = session.scalars(q).all()
        by_scene: dict[tuple[str, str, int], dict] = defaultdict(lambda: {'packs': 0, 'photos': 0})
        total_photos = 0
        for p in packs:
            n = session.scalar(select(func.count(PhotoLibraryItem.id)).where(PhotoLibraryItem.pack_id == p.id)) or 0
            key = (p.character_id, p.scene, p.relationship_level)
            by_scene[key]['packs'] += 1
            by_scene[key]['photos'] += int(n)
            total_photos += int(n)
        return {
            'total_packs': len(packs),
            'total_photos': total_photos,
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
