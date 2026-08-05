from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from services.user_service import get_state, get_user, update_state

FUTURE_HOOK = re.compile(r'\b(сегодня вечером|вечером|завтра|потом|позже|собеседован|встреч|экзамен|поеду|иду на|буду |созвон|дедлайн|врач|покупать|куплю)\b', re.I)

LIFE_BY_DAYPART = {
    'morning': [
        ('дома', 'собираюсь и разбираюсь с утренними делами', 'спокойное'),
        ('кафе', 'взяла что-нибудь попить и немного просыпаюсь', 'лёгкое'),
        ('на улице', 'вышла ненадолго по делам', 'бодрое'),
    ],
    'afternoon': [
        ('в городе', 'бегаю по делам', 'обычное'),
        ('кафе', 'сделала короткую паузу', 'спокойное'),
        ('магазин', 'зашла кое-что посмотреть', 'любопытное'),
        ('парк', 'немного гуляю', 'лёгкое'),
    ],
    'evening': [
        ('дома', 'решаю, чем заняться вечером', 'уютное'),
        ('ресторан', 'вышла поужинать', 'хорошее'),
        ('набережная', 'вышла пройтись', 'спокойное'),
        ('бар', 'заскочила ненадолго вечером', 'игривое'),
    ],
    'night': [
        ('дома', 'уже отдыхаю после дня', 'тихое'),
        ('дома', 'залипла в телефон вместо сна', 'сонное'),
    ],
}


def _local_now(telegram_id: int) -> datetime:
    user = get_user(telegram_id)
    tz_name = getattr(user, 'timezone', None) or 'UTC'
    try:
        return datetime.now(timezone.utc).astimezone(ZoneInfo(tz_name))
    except Exception:
        return datetime.now(timezone.utc)


def _daypart(hour: int) -> str:
    if 6 <= hour < 11:
        return 'morning'
    if 11 <= hour < 18:
        return 'afternoon'
    if 18 <= hour < 23:
        return 'evening'
    return 'night'


def ensure_life_state(telegram_id: int, *, force: bool = False):
    """Keep a lightweight fictional daily-life state without pretending it is real-world telemetry."""
    state = get_state(telegram_id)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    age_hours = 99.0
    if getattr(state, 'updated_at', None):
        age_hours = max(0.0, (now_utc - state.updated_at).total_seconds() / 3600.0)
    if not force and state.activity and state.location and age_hours < 3.0:
        return state

    local = _local_now(telegram_id)
    part = _daypart(local.hour)
    # Stable-ish within a daypart: user gets continuity instead of a new life every message.
    seed = f'{telegram_id}:{local.date().isoformat()}:{part}'
    rng = random.Random(seed)
    location, activity, mood = rng.choice(LIFE_BY_DAYPART[part])
    energy = {'morning': .62, 'afternoon': .72, 'evening': .68, 'night': .38}[part]
    update_state(telegram_id, location=location, activity=activity, mood=mood, energy=energy)
    return get_state(telegram_id)


def state_context(telegram_id: int) -> str:
    s = ensure_life_state(telegram_id)
    parts = [f"настроение: {s.mood}", f"энергия: {'низкая' if s.energy < .4 else 'обычная' if s.energy < .75 else 'высокая'}"]
    if s.activity: parts.append(f"сейчас по условной истории Анны: {s.activity}")
    if s.location: parts.append(f"текущая локация истории: {s.location}")
    if s.outfit: parts.append(f"последний показанный образ: {s.outfit}")
    if s.hairstyle: parts.append(f"последняя причёска: {s.hairstyle}")
    if s.pending_hook: parts.append(f"незакрытая тема пользователя, к которой можно естественно вернуться: {s.pending_hook}")
    return '; '.join(parts) + '. Используй только когда уместно; не перечисляй это пользователю списком и не утверждай, что это реальные внешние события.'


def softly_evolve_state(telegram_id: int, user_text: str):
    s = ensure_life_state(telegram_id)
    kwargs = {}
    t = (user_text or '').lower()
    if any(x in t for x in ('ахах','😂','шут','смеш')):
        kwargs['playfulness'] = min(1.0, s.playfulness + .05)
        kwargs['mood'] = 'игривое'
    elif any(x in t for x in ('груст','плохо','устал','тяжело')):
        kwargs['mood'] = 'спокойное и внимательное'
    if FUTURE_HOOK.search(user_text or ''):
        # Keep the user's wording so a later proactive message can continue the exact story.
        kwargs['pending_hook'] = (user_text or '').strip()[:420]
    if random.random() < .08:
        kwargs['energy'] = max(.25, min(.95, s.energy + random.uniform(-.12,.12)))
    if kwargs:
        update_state(telegram_id, **kwargs)
