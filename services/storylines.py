"""V3.78.0: «🎬 Сюжеты» — Premium role-play storylines on every girl's page.

The owner: «сюжеты на всех девушек… нет бесплатных… только премиум… чтобы
прям был вау». Seven per girl live in ``storylines_data.PLOTS``.

A storyline plays as an episode in three acts, moved by the number of his
messages: the setup, the heat, the finale. After the finale it counts as
passed («🎬 Сюжет пройден») and the app offers her next one. He picks how
hot it goes before the start (owner: «уровень человек сам выставил») and can
leave it any time with «Без ролей».
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from services import dialog_store
from services.storylines_data import PLOTS

logger = logging.getLogger(__name__)

ACTIVE_HOURS = 24
# his messages inside the plot: 1–5 setup, 6–13 heat, 14–17 climax, 18 finale
ACT2_AT = 6
ACT3_AT = 14
FINALE_AT = 18
HEATS = ('soft', 'hot', 'wild')
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


_BY_CHAR: dict[str, tuple[Plot, ...]] = {
    cid: tuple(Plot(key, cid, emoji, title, teaser, her, his, place, opening)
               for key, emoji, title, teaser, her, his, place, opening in items)
    for cid, items in PLOTS.items()
}


def for_character(character_id: str) -> tuple[Plot, ...]:
    return _BY_CHAR.get(character_id or '', ())


def get(character_id: str, key: str) -> Plot | None:
    return next((p for p in for_character(character_id) if p.key == (key or '').strip()), None)


def next_after(character_id: str, key: str) -> Plot | None:
    plots = for_character(character_id)
    for i, p in enumerate(plots):
        if p.key == key:
            return plots[i + 1] if i + 1 < len(plots) else None
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user(telegram_id: int) -> dict:
    try:
        raw = dict(_state.get(int(telegram_id)) or {})
    except Exception:
        raw = {}
    # V3.78.0 first shape kept {char: {key, until}} at the top level
    active = dict(raw.get('active') or {k: v for k, v in raw.items()
                                         if isinstance(v, dict) and 'key' in v})
    return {'active': active, 'done': dict(raw.get('done') or {}), 'just_done': dict(raw.get('just_done') or {})}


def _save(telegram_id: int, data: dict) -> None:
    try:
        _state[int(telegram_id)] = data
    except Exception:
        logger.exception('storyline save failed user=%s', telegram_id)


def start(telegram_id: int, plot: Plot, heat: str = 'hot') -> None:
    data = _user(telegram_id)
    until = _now() + timedelta(hours=ACTIVE_HOURS)
    data['active'][plot.character_id] = {'key': plot.key, 'until': until.isoformat(timespec='seconds'),
                                         'heat': heat if heat in HEATS else 'hot', 'n': 0}
    data['just_done'].pop(plot.character_id, None)
    _save(telegram_id, data)


def stop(telegram_id: int, character_id: str) -> bool:
    data = _user(telegram_id)
    if data['active'].pop(character_id, None) is None:
        return False
    _save(telegram_id, data)
    return True


def _item(telegram_id: int, character_id: str) -> dict | None:
    item = _user(telegram_id)['active'].get(character_id) or {}
    try:
        until = datetime.fromisoformat(item.get('until') or '')
    except (TypeError, ValueError):
        return None
    return item if until >= _now() else None


def active(telegram_id: int, character_id: str) -> Plot | None:
    item = _item(telegram_id, character_id)
    return get(character_id, item.get('key', '')) if item else None


def heat(telegram_id: int, character_id: str) -> str | None:
    item = _item(telegram_id, character_id)
    return (item.get('heat') or 'hot') if item else None


def act_of(n: int) -> int:
    return 1 if n < ACT2_AT else (2 if n < ACT3_AT else 3)


def status(telegram_id: int, character_id: str, *, consume: bool = False) -> dict:
    """For the app: the running plot (title, act, heat), passed keys and a
    plot that has just been passed (consumed once when ``consume``)."""
    data = _user(telegram_id)
    item = _item(telegram_id, character_id)
    plot = get(character_id, item.get('key', '')) if item else None
    just = data['just_done'].get(character_id)
    out = {
        'active': ({'key': plot.key, 'title': plot.title, 'emoji': plot.emoji,
                    'act': act_of(int(item.get('n') or 0)), 'heat': item.get('heat') or 'hot'} if plot else None),
        'done': list(data['done'].get(character_id) or []),
        'just_done': None,
    }
    if just:
        passed = get(character_id, just)
        nxt = next_after(character_id, just)
        out['just_done'] = {'key': just, 'title': passed.title if passed else '',
                            'next': ({'key': nxt.key, 'title': nxt.title, 'emoji': nxt.emoji} if nxt else None)}
        if consume:
            data['just_done'].pop(character_id, None)
            _save(telegram_id, data)
    return out


def public_list(character_id: str) -> list[dict]:
    """What the app shows on her page: no roles, no opening line."""
    return [{'key': p.key, 'emoji': p.emoji, 'title': p.title, 'teaser': p.teaser}
            for p in for_character(character_id)]


HEAT_LINES = {
    'soft': ('УРОВЕНЬ (он выбрал «🌸 Нежно»): романтика и флирт, нежность, лёгкие намёки и поцелуи; '
             'без откровенных описаний, даже если этап отношений позволяет больше.'),
    'hot': ('УРОВЕНЬ (он выбрал «🔥 Горячо»): страстно и смело — откровенные намёки, желания, '
            'горячие описания; насколько подробно — по обычным правилам этого чата.'),
    'wild': ('УРОВЕНЬ (он выбрал «😈 Без тормозов»): максимально откровенно и пошло, без стеснения '
             'и без «давай не будем»; ты ведёшь и сама предлагаешь ещё смелее.'),
}

ACT_LINES = {
    1: 'АКТ 1 из 3 — завязка: флирт, напряжение, игра ролью; к главному пока не переходи, разогревай.',
    2: 'АКТ 2 из 3 — накал: сцена становится горячее, ты сама делаешь шаг к главному.',
    3: 'АКТ 3 из 3 — кульминация: самая яркая часть сцены, всё, к чему вы шли.',
}
FINALE_LINE = ('ФИНАЛ СЮЖЕТА: в этом ответе доведи сцену до красивого завершения — яркий последний момент '
               'и тёплое послевкусие, одна фраза-намёк, что продолжение было бы ещё интереснее. '
               'Это последний ответ в роли.')


def direction(p: Plot, name: str = '', *, n: int = 0, heat_level: str = 'hot') -> str:
    who = name or 'она'
    stage = FINALE_LINE if n >= FINALE_AT else ACT_LINES[act_of(n)]
    return (
        f'СЮЖЕТ «{p.title}» (он сам выбрал его). Ты, {who}, сейчас играешь роль: {p.her_role}. '
        f'Он в сюжете: {p.his_role}. Место и время: {p.place}. Завязка: {p.teaser}. '
        f'Ты начала сцену так: «{p.opening}». '
        f'{stage} {HEAT_LINES.get(heat_level, HEAT_LINES["hot"])} '
        'Оба взрослые, всё по обоюдному желанию. Живи ролью: от первого лица, короткие действия '
        'в *звёздочках*, живые разговорные реплики; сама двигай сюжет вперёд, дразни, создавай '
        'напряжение, каждый ответ заканчивай так, чтобы ему хотелось ответить. Не выходи из роли, '
        'не говори, что это игра или сценарий, не пересказывай завязку.'
    )


def direction_for(telegram_id: int, character_id: str, name: str = '', *, tick: bool = False) -> str:
    """The scene note for her next reply. ``tick`` counts his message (the
    chat pipeline passes it once per reply); the finale reply closes the plot."""
    try:
        data = _user(int(telegram_id))
        item = _item(int(telegram_id), character_id)
        plot = get(character_id, item.get('key', '')) if item else None
        if not plot:
            return ''
        n = int(item.get('n') or 0) + (1 if tick else 0)
        line = direction(plot, name, n=n, heat_level=item.get('heat') or 'hot')
        if tick:
            if n >= FINALE_AT:
                data['active'].pop(character_id, None)
                done = list(data['done'].get(character_id) or [])
                if plot.key not in done:
                    done.append(plot.key)
                data['done'][character_id] = done
                data['just_done'][character_id] = plot.key
            else:
                item = dict(item, n=n)
                data['active'][character_id] = item
            _save(int(telegram_id), data)
        return line
    except Exception:
        logger.exception('storyline direction failed user=%s', telegram_id)
        return ''
