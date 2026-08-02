"""Developer-only relationship stage override.

This is intentionally in-memory: it never changes the user's real relationship
scores and disappears after a process restart. It lets the bot owner test every
stage, including photo locks and chat tone, without polluting real data.
"""
from __future__ import annotations

from typing import Optional

STAGES = (
    "stranger",
    "acquaintance",
    "close",
    "intimate",
    "deeply_connected",
)

_overrides: dict[int, str] = {}


def set_stage(user_id: int, stage: str) -> bool:
    if stage not in STAGES:
        return False
    _overrides[user_id] = stage
    return True


def clear_stage(user_id: int) -> None:
    _overrides.pop(user_id, None)


def get_stage(user_id: int) -> Optional[str]:
    return _overrides.get(user_id)


def is_active(user_id: int) -> bool:
    return user_id in _overrides
