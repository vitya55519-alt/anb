from __future__ import annotations
import random
from datetime import datetime
from services.user_service import get_state, update_state

def state_context(telegram_id: int) -> str:
    s = get_state(telegram_id)
    parts = [f"настроение: {s.mood}", f"энергия: {'низкая' if s.energy < .4 else 'обычная' if s.energy < .75 else 'высокая'}"]
    if s.activity: parts.append(f"занята: {s.activity}")
    if s.location: parts.append(f"локация образа: {s.location}")
    if s.outfit: parts.append(f"текущий образ: {s.outfit}")
    if s.hairstyle: parts.append(f"причёска: {s.hairstyle}")
    if s.pending_hook: parts.append(f"незакрытая тема: {s.pending_hook}")
    return "; ".join(parts) + ". Используй только когда уместно и не перечисляй это пользователю списком."

def softly_evolve_state(telegram_id: int, user_text: str):
    s = get_state(telegram_id)
    kwargs = {}
    t = (user_text or '').lower()
    if any(x in t for x in ('ахах','😂','шут','смеш')):
        kwargs['playfulness'] = min(1.0, s.playfulness + .05)
        kwargs['mood'] = 'игривое'
    elif any(x in t for x in ('груст','плохо','устал','тяжело')):
        kwargs['mood'] = 'спокойное и внимательное'
    if random.random() < .08:
        kwargs['energy'] = max(.25, min(.95, s.energy + random.uniform(-.12,.12)))
    if kwargs: update_state(telegram_id, **kwargs)
