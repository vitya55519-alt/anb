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
)

STAGE_LABELS = {
    "stranger": "1 · Знакомство",
    "acquaintance": "2 · Симпатия",
    "close": "3 · Флирт",
    "intimate": "4 · Влюблённость",
    "deeply_connected": "5 · Любовники",
    "committed": "6 · Наша история",
    "devoted": "7 · Родственные души (премиум)",
    "soulmate": "8 · Одно целое (премиум)",
}

_overrides: dict[int, str] = {}

def set_stage(user_id: int, stage: str) -> str:
    if stage not in STAGES:
        raise ValueError(stage)
    _overrides[int(user_id)] = stage
    return stage

def clear_stage(user_id: int) -> None:
    _overrides.pop(int(user_id), None)

def get_stage(user_id: int) -> str | None:
    return _overrides.get(int(user_id))

def get_status(user_id: int) -> str:
    return _overrides.get(int(user_id), "off")
