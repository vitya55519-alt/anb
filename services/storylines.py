"""V3.78.0: «🎬 Сюжеты» — Premium role-play storylines on every girl's page.

The owner: «сюжеты на всех девушек… нет бесплатных… только премиум… чтобы
прям был вау». Seven per girl live in ``storylines_data.PLOTS``. Starting
one puts her opening line into the dialog and keeps the scene direction on
her replies for ACTIVE_HOURS (same mechanism as the scenario cards).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from services import dialog_store
from services.storylines_data import PLOTS

logger = logging.getLogger(__name__)

ACTIVE_HOURS = 24
_state = dialog_store.DialogStore('storylines')


@dataclass(frozen=True)
class Plot:
    key: str
    character_id: str
    emoji: str
    title: str
    teaser: str
    her_role: str
    his_role: str
    place: str
    opening: str

    @property
    def uid(self) -> str:
        return f'{self.character_id}:{self.key}'


_BY_CHAR: dict[str, tuple[Plot, ...]] = {
    cid: tuple(Plot(key, cid, emoji, title, teaser, her, his, place, opening)
               for key, emoji, title, teaser, her, his, place, opening in items)
    for cid, items in PLOTS.items()
}


def for_character(character_id: str) -> tuple[Plot, ...]:
    return _BY_CHAR.get(character_id or '', ())


def get(character_id: str, key: str) -> Plot | None:
    return next((p for p in for_character(character_id) if p.key == (key or '').strip()), None)


def public_list(character_id: str) -> list[dict]:
    """What the app shows on her page: no roles, no opening line."""
    return [{'key': p.key, 'emoji': p.emoji, 'title': p.title, 'teaser': p.teaser}
            for p in for_character(character_id)]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _active_map(telegram_id: int) -> dict:
    try:
        return dict(_state.get(int(telegram_id)) or {})
    except Exception:
        return {}


def start(telegram_id: int, plot: Plot) -> None:
    data = _active_map(telegram_id)
    until = _now() + timedelta(hours=ACTIVE_HOURS)
    data[plot.character_id] = {'key': plot.key, 'until': until.isoformat(timespec='seconds')}
    try:
        _state[int(telegram_id)] = data
    except Exception:
        logger.exception('storyline save failed user=%s', telegram_id)


def stop(telegram_id: int, character_id: str) -> bool:
    data = _active_map(telegram_id)
    if data.pop(character_id, None) is None:
        return False
    _state[int(telegram_id)] = data
    return True


def active(telegram_id: int, character_id: str) -> Plot | None:
    item = _active_map(telegram_id).get(character_id) or {}
    try:
        until = datetime.fromisoformat(item.get('until') or '')
    except (TypeError, ValueError):
        return None
    if until < _now():
        return None
    return get(character_id, item.get('key', ''))


def direction(p: Plot, name: str = '') -> str:
    who = name or 'она'
    return (
        f'СЮЖЕТ «{p.title}» (он сам выбрал его). Ты, {who}, сейчас играешь роль: {p.her_role}. '
        f'Он в сюжете: {p.his_role}. Место и время: {p.place}. Завязка: {p.teaser}. '
        f'Ты начала сцену так: «{p.opening}». '
        'Оба взрослые, всё по обоюдному желанию. Живи ролью: от первого лица, короткие действия '
        'в *звёздочках*, живые разговорные реплики; сама двигай сюжет вперёд и накаляй его, '
        'дразни, создавай напряжение, каждый ответ заканчивай так, чтобы ему хотелось ответить. '
        'Не выходи из роли, не говори, что это игра или сценарий, не пересказывай завязку. '
        'Откровенность — по обычным правилам этого чата. Если он явно хочет закончить — мягко выйди из роли.'
    )


def direction_for(telegram_id: int, character_id: str, name: str = '') -> str:
    try:
        p = active(int(telegram_id), character_id)
    except Exception:
        return ''
    return direction(p, name) if p else ''
