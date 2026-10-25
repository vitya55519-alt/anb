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

def get_stage(user_id: int, character_id: str | None = None) -> str | None:
    """The owner's /testlevel first; then (V3.83.0) the level a Premium user
    picked for this girl. Callers without a girl see only /testlevel."""
    uid = int(user_id)
    if uid not in _loaded:
        _loaded.add(uid)
        stage = _db_read(uid)
        if stage:
            _overrides[uid] = stage
    if uid in _overrides:
        return _overrides[uid]
    if character_id:
        return picked_stage(uid, character_id)
    return None


# V3.83.0: «с Premium можно выбрать любой уровень общения» — per girl, 1-10.
# Stored as {character_id: stage}; it only applies while Premium is active,
# and never touches the real scores, so real progress resumes without it.
_PICKS_KEY = 'level_pick'
_picks: dict[int, dict] = {}


def _picks_store():
    from services.dialog_store import DialogStore
    return DialogStore(_PICKS_KEY)


def _load_picks(uid: int) -> dict:
    if uid not in _picks:
        try:
            _picks[uid] = dict(_picks_store().get(uid) or {})
        except Exception:
            _picks[uid] = {}
    return _picks[uid]


def _premium(uid: int) -> bool:
    try:
        from config import ADMIN_TELEGRAM_IDS
        if uid in ADMIN_TELEGRAM_IDS:
            return True
        from services.access_service import is_premium
        return bool(is_premium(uid))
    except Exception:
        return False


def picked_stages(user_id: int) -> dict:
    """{character_id: stage} the user picked, empty without Premium."""
    uid = int(user_id)
    picks = _load_picks(uid)
    if not picks or not _premium(uid):
        return {}
    return {cid: st for cid, st in picks.items() if st in STAGES}


def picked_stage(user_id: int, character_id: str) -> str | None:
    uid = int(user_id)
    stage = _load_picks(uid).get(character_id)
    if stage not in STAGES or not _premium(uid):
        return None
    return stage


def pick_stage(user_id: int, character_id: str, stage: str | None) -> None:
    """Set (or with None clear) his chosen level for this girl."""
    uid = int(user_id)
    picks = dict(_load_picks(uid))
    if stage is None:
        picks.pop(character_id, None)
    elif stage in STAGES:
        picks[character_id] = stage
    else:
        raise ValueError(stage)
    _picks[uid] = picks
    try:
        store = _picks_store()
        if picks:
            store[uid] = picks
        else:
            store.pop(uid, None)
    except Exception:
        pass

def get_status(user_id: int) -> str:
    return get_stage(user_id) or "off"
