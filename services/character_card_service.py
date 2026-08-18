from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from models.app_models import CharacterCard
from services.db import SessionLocal


STATUS_LABELS = {
    "active": "активна",
    "soon": "скоро",
    "locked": "закрыта",
    "premium": "Premium",
}

DEFAULT_CARDS = {
    "anna_01": {
        "display_name": "Анна",
        "age": 26,
        "short_bio": "Тёплая, общительная, уверенная и немного вредная. Любит вечерний город, музыку, стильные образы и лёгкие подколы.",
        "status": "active",
        "button_emoji": "👩🏻",
        "is_visible": True,
    },
    "alena_01": {
        "display_name": "Emily",
        "age": 25,
        "short_bio": "Яркая, уверенная и самостоятельная. Любит street fashion, автомобили, новые места и вечерний город.",
        "status": "soon",
        "button_emoji": "👱‍♀️",
        "is_visible": True,
    },
}


@dataclass(frozen=True)
class CharacterCardView:
    character_id: str
    display_name: str
    age: int
    short_bio: str
    status: str
    button_emoji: str
    is_visible: bool
    card_photo_file_id: str | None

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def button_text(self) -> str:
        return f"{self.button_emoji} {self.display_name} · {self.status_label}"


def _to_view(row: CharacterCard) -> CharacterCardView:
    return CharacterCardView(
        character_id=row.character_id,
        display_name=row.display_name,
        age=int(row.age or 18),
        short_bio=row.short_bio or "",
        status=row.status or "soon",
        button_emoji=row.button_emoji or "👩",
        is_visible=bool(row.is_visible),
        card_photo_file_id=row.card_photo_file_id,
    )


def ensure_default_cards() -> None:
    with SessionLocal() as session:
        changed = False
        for character_id, defaults in DEFAULT_CARDS.items():
            row = session.get(CharacterCard, character_id)
            if row is None:
                session.add(CharacterCard(character_id=character_id, **defaults))
                changed = True
                continue
            # One-time backward-compatible public rename. Keep the internal id so existing
            # photo-library and DB references do not break. Do not overwrite a custom name.
            if character_id == "alena_01" and (row.display_name or "").strip() in {"Алёна", "Алена"}:
                row.display_name = "Emily"
                if not row.short_bio or "street fashion" in row.short_bio:
                    row.short_bio = defaults["short_bio"]
                changed = True
        if changed:
            session.commit()


def list_cards(*, visible_only: bool = False) -> list[CharacterCardView]:
    ensure_default_cards()
    with SessionLocal() as session:
        query = session.query(CharacterCard)
        if visible_only:
            query = query.filter(CharacterCard.is_visible.is_(True))
        rows = query.order_by(CharacterCard.character_id.asc()).all()
        return [_to_view(row) for row in rows]


def get_card(character_id: str) -> CharacterCardView | None:
    ensure_default_cards()
    with SessionLocal() as session:
        row = session.get(CharacterCard, character_id)
        return _to_view(row) if row else None


def update_card(character_id: str, **changes) -> CharacterCardView:
    ensure_default_cards()
    allowed = {
        "display_name", "age", "short_bio", "status", "button_emoji",
        "is_visible", "card_photo_file_id",
    }
    clean = {k: v for k, v in changes.items() if k in allowed}
    if "status" in clean and clean["status"] not in STATUS_LABELS:
        raise ValueError("unknown card status")
    with SessionLocal() as session:
        row = session.get(CharacterCard, character_id)
        if row is None:
            defaults = DEFAULT_CARDS.get(character_id, {
                "display_name": character_id,
                "age": 18,
                "short_bio": "",
                "status": "soon",
                "button_emoji": "👩",
                "is_visible": True,
            })
            row = CharacterCard(character_id=character_id, **defaults)
            session.add(row)
        for key, value in clean.items():
            setattr(row, key, value)
        session.commit()
        session.refresh(row)
        return _to_view(row)


def reset_card(character_id: str) -> CharacterCardView:
    defaults = DEFAULT_CARDS.get(character_id)
    if not defaults:
        raise ValueError("no defaults for character")
    return update_card(character_id, **defaults, card_photo_file_id=None)


def create_card(character_id: str, display_name: str, age: int, short_bio: str, button_emoji: str = "👩") -> CharacterCardView:
    character_id = (character_id or '').strip().lower()
    display_name = (display_name or '').strip()
    if not character_id or not display_name:
        raise ValueError("id и имя обязательны")
    if not re.match(r'^[a-z0-9_]+$', character_id):
        raise ValueError("id только маленькие латинские буквы, цифры и подчёркивание")
    if not 18 <= age <= 99:
        raise ValueError("возраст 18–99")
    with SessionLocal() as session:
        if session.get(CharacterCard, character_id):
            raise ValueError("такой id уже есть")
        row = CharacterCard(
            character_id=character_id,
            display_name=display_name,
            age=age,
            short_bio=short_bio or "",
            status="soon",
            button_emoji=button_emoji or "👩",
            is_visible=True,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_view(row)


def delete_card(character_id: str) -> bool:
    if character_id in DEFAULT_CARDS:
        raise ValueError("стандартных персонажей нельзя удалить")
    with SessionLocal() as session:
        row = session.get(CharacterCard, character_id)
        if not row:
            return False
        session.delete(row)
        session.commit()
        return True
