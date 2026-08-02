from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
from config import CHARACTER_DIR, CHARACTER_ID


@lru_cache(maxsize=32)
def get_character(character_id: str) -> dict:
    path = Path(CHARACTER_DIR) / f"{character_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Character profile not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_active_character() -> dict:
    return get_character(CHARACTER_ID)
