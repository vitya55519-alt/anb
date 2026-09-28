"""V3.30.0 static pins: the cosplay photoshoot (the FreeKassa REST-API half
of this release retired with the kassa itself in V3.44.21 — Platega needs
no request signatures; its X-MerchantId/X-Secret headers are pinned by
test_v34421).

The surviving v3.30.0 feature: the explicit adult menu buttons are gone and
a token-priced cosplay scene with a costume picker exists.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def test_version_bumped():
    assert VERSION in ('3.44.4', '3.44.3', '3.43.7', '3.43.6', '3.43.5', '3.43.4', '3.43.3', '3.43.2', '3.43.1', '3.43.0', '3.42.2', '3.42.1', '3.42.0', '3.41.0', '3.40.0', '3.30.0', '3.30.1', '3.30.2', '3.30.3', '3.30.4', '3.30.5', '3.30.6', '3.30.7', '3.30.8', '3.30.9', '3.31.0', '3.31.1', '3.31.2', '3.31.3', '3.31.4', '3.31.5', '3.31.6', '3.31.7', '3.31.8', '3.32.0', '3.32.1', '3.33.0', '3.33.1', '3.34.0', '3.34.1', '3.35.0', '3.36.0', '3.37.0', '3.38.0', '3.39.0')


def test_cosplay_token_cost_config():
    assert 'COSPLAY_TOKEN_COST = max(1, int(os.getenv("COSPLAY_TOKEN_COST", "10")))' in CONFIG


def test_photo_menu_has_no_explicit_adult_buttons():
    tree = ast.parse(MAIN)
    order = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(t, 'id', '') == 'PHOTO_MENU_ORDER' for t in node.targets
        ):
            order = [elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)]
    assert order is not None and order
    assert 'nude' not in order and 'tease' not in order
    # labels and backend registries stay for old library photos
    assert "'nude': '🔥 Обнажённая'" in MAIN
    assert "'tease': '🍑 Дразнит'" in MAIN
    assert "'nude':" in PHOTO and "'tease':" in PHOTO


def test_cosplay_scene_and_costumes():
    assert "'cosplay':" in PHOTO
    # V3.31.5: cosplay is available at every relationship level (owner request)
    assert "'cosplay': 1," in PHOTO
    assert 'COSPLAY_COSTUMES = {' in MAIN
    assert 'async def cosplay_start(' in MAIN
    assert 'async def cosplay_pick(' in MAIN
    assert "PhotoRequest(scene='cosplay', clothing=costume[1], hairstyle=costume[2], hair_color=costume[3])" in MAIN
    assert 'spend_tokens(cq.from_user.id, COSPLAY_TOKEN_COST)' in MAIN
    # tokens come back when the job cannot start (busy/budget guard)
    assert 'add_tokens(cq.from_user.id, COSPLAY_TOKEN_COST)' in MAIN
    # photo-menu entry point
    assert "callback_data='cosplay:start'" in MAIN
    assert '🎭 Косплей-фотосет' in MAIN
