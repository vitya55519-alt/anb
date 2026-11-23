"""V3.166.4 (Блок 1, владелец): кэш стартовых кадров — по 4 на героиню и сценарий.

Механика тизера: он тапает чип под её первой репликой, и если для пары
(героиня × заготовка) уже лежит четвёрка кадров, сервер просто берёт один из
него — моментально, без обращения к генератору и без денег. Четвёрки нет —
дорисовывается ровно один кадр, который остаётся всем следующим. Владелец:
«на связку character_id + greeting_id может храниться максимум 4 фотографии».

Байры живут в строке (PostgreSQL), а не на диске Railway: кадр обязан открыться
у следующего незнакомца после любого редеплоя, а не только у того, в чьем чате
его нарисовали. ``file_id`` — копия для Telegram; для нарисованных кадров она
пока пустая, заполняется, только если кадр когда-нибудь придёт из Telegram.
"""
from __future__ import annotations

import logging
import random

from sqlalchemy import func, select

from config import STARTER_PHOTOS_PER_SCENARIO
from models.app_models import StarterPhotoCache
from services.db import SessionLocal

logger = logging.getLogger(__name__)

LIMIT = STARTER_PHOTOS_PER_SCENARIO


def count(character_id: str, greeting_id: int) -> int:
    try:
        with SessionLocal() as s:
            return int(s.scalar(
                select(func.count(StarterPhotoCache.id)).where(
                    StarterPhotoCache.character_id == character_id,
                    StarterPhotoCache.greeting_id == int(greeting_id))
            ) or 0)
    except Exception:
        logger.warning('starter cache count failed girl=%s greeting=%s', character_id, greeting_id)
        return 0


def is_full(character_id: str, greeting_id: int) -> bool:
    return count(character_id, greeting_id) >= LIMIT


def pick(character_id: str, greeting_id: int) -> int | None:
    """Случайный закешированный кадр пары — id строки, «ORDER BY RANDOM() LIMIT 1».

    Не найдено ничего (или в паре нет байров) — None: тогда вызывающий рисует
    новый кадр и кладёт его в кэш.
    """
    try:
        with SessionLocal() as s:
            rows = list(s.execute(
                select(StarterPhotoCache.id).where(
                    StarterPhotoCache.character_id == character_id,
                    StarterPhotoCache.greeting_id == int(greeting_id),
                    StarterPhotoCache.photo_bytes.is_not(None))
            ).scalars().all())
    except Exception:
        logger.warning('starter cache pick failed girl=%s greeting=%s', character_id, greeting_id)
        return None
    return random.choice(rows) if rows else None


def pick_any(character_id: str) -> int | None:
    """V3.169: a stock frame of the same girl from ANY of her scenarios — the $0
    stand-in when the exact pair has none, instead of a live SpicyAPI render."""
    try:
        with SessionLocal() as s:
            rows = list(s.execute(
                select(StarterPhotoCache.id).where(
                    StarterPhotoCache.character_id == character_id,
                    StarterPhotoCache.photo_bytes.is_not(None))).scalars().all())
    except Exception:
        logger.warning('starter cache pick_any failed girl=%s', character_id)
        return None
    return random.choice(rows) if rows else None


def save(character_id: str, greeting_id: int, photo_bytes: bytes, file_id: str = '') -> int | None:
    """Положить нарисованный кадр в пару; сверх четвёрки не кладём никогда."""
    if not photo_bytes or not character_id or not int(greeting_id):
        return None
    try:
        with SessionLocal() as s:
            held = int(s.scalar(
                select(func.count(StarterPhotoCache.id)).where(
                    StarterPhotoCache.character_id == character_id,
                    StarterPhotoCache.greeting_id == int(greeting_id))
            ) or 0)
            if held >= LIMIT:
                return None
            row = StarterPhotoCache(character_id=character_id, greeting_id=int(greeting_id),
                                    file_id=file_id or None, photo_bytes=photo_bytes)
            s.add(row)
            s.commit()
            return int(row.id)
    except Exception:
        logger.warning('starter cache save failed girl=%s greeting=%s', character_id, greeting_id)
        return None


def body_for(cache_id: int) -> bytes | None:
    try:
        with SessionLocal() as s:
            row = s.get(StarterPhotoCache, int(cache_id))
            return bytes(row.photo_bytes) if row and row.photo_bytes else None
    except Exception:
        logger.warning('starter cache read failed id=%s', cache_id)
        return None


def list_for(character_id: str, greeting_id: int) -> list[dict]:
    """Кухня владельцу: что лежит в одной паре (без байров — только метки)."""
    try:
        with SessionLocal() as s:
            rows = list(s.scalars(
                select(StarterPhotoCache).where(
                    StarterPhotoCache.character_id == character_id,
                    StarterPhotoCache.greeting_id == int(greeting_id))
                .order_by(StarterPhotoCache.id)
            ))
        return [{'id': int(r.id), 'created_at': r.created_at, 'has_photo': bool(r.photo_bytes),
                 'file_id': r.file_id or ''} for r in rows]
    except Exception:
        logger.warning('starter cache list failed girl=%s greeting=%s', character_id, greeting_id)
        return []


def counts_for(character_id: str) -> dict[int, int]:
    """Сколько кадров собрано у каждой заготовки этой героини — экран «Сценарии»."""
    try:
        with SessionLocal() as s:
            rows = s.execute(
                select(StarterPhotoCache.greeting_id, func.count(StarterPhotoCache.id))
                .where(StarterPhotoCache.character_id == character_id).group_by(StarterPhotoCache.greeting_id)
            ).all()
        return {int(r[0]): int(r[1]) for r in rows}
    except Exception:
        logger.warning('starter cache counts failed girl=%s', character_id)
        return {}


def delete(cache_id: int) -> bool:
    """Удаление одного кадра: их станет 3 из 4, и следующий тап дорисует новый."""
    try:
        with SessionLocal() as s:
            row = s.get(StarterPhotoCache, int(cache_id))
            if not row:
                return False
            s.delete(row)
            s.commit()
        return True
    except Exception:
        logger.warning('starter cache delete failed id=%s', cache_id)
        return False
