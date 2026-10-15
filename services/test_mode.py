"""Owner-only relationship stage overrides for testing.

Overrides live in memory and never modify real relationship scores.
"""
from __future__ import annotations

STAGES = (
    "stranger",
    "acquaintance",
    "close",
    "intimate",
    "deeply_connected",
    "committed",
    "devoted",
    "soulmate",
    "voyage",
    "eternal",
)

STAGE_LABELS = {
    "stranger": "1 · Знакомство",
    "acquaintance": "2 · Симпатия",
    "close": "3 · Искра",
    "intimate": "4 · Влюблённость / Искушение",
    "deeply_connected": "5 · Первое свидание / Игра",
    "committed": "6 · Только ты / Без тормозов",
    "devoted": "7 · Наша история / Тайная связь (премиум)",
    "soulmate": "8 · Под одной крышей / Одержимость (премиум)",
    "voyage": "9 · Путешествие / Запретная зона (премиум)",
    "eternal": "10 · Одно целое / Без правил (премиум)",
}

_overrides: dict[int, str] = {}
# V3.60.9: overrides survive a redeploy — memory is a cache over the
# admin_test_stages table. Users never looked up stay out of the cache.
_loaded: set[int] = set()


def _db_write(user_id: int, stage: str | None) -> None:
    try:
        from services.db import SessionLocal
        from models.app_models import AdminTestStage
        with SessionLocal() as s:
            row = s.get(AdminTestStage, int(user_id))
            if stage is None:
                if row is not None:
                    s.delete(row)
            elif row is None:
                s.add(AdminTestStage(user_id=int(user_id), stage=stage))
            else:
                row.stage = stage
            s.commit()
    except Exception:
        pass


def _db_read(user_id: int) -> str | None:
    try:
        from services.db import SessionLocal
        from models.app_models import AdminTestStage
        with SessionLocal() as s:
            row = s.get(AdminTestStage, int(user_id))
            return row.stage if row is not None and row.stage in STAGES else None
    except Exception:
        return None


def set_stage(user_id: int, stage: str) -> str:
    if stage not in STAGES:
        raise ValueError(stage)
    _overrides[int(user_id)] = stage
    _loaded.add(int(user_id))
    _db_write(user_id, stage)
    return stage

def clear_stage(user_id: int) -> None:
    _overrides.pop(int(user_id), None)
    _loaded.add(int(user_id))
    _db_write(user_id, None)

def get_stage(user_id: int) -> str | None:
    uid = int(user_id)
    if uid not in _loaded:
        _loaded.add(uid)
        stage = _db_read(uid)
        if stage:
            _overrides[uid] = stage
    return _overrides.get(uid)

def get_status(user_id: int) -> str:
    return get_stage(user_id) or "off"
