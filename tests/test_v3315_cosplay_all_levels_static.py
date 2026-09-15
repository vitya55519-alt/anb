"""Static regression tests for v3.31.5: cosplay available at every level.

Owner request: «Сделай, чтобы косплей был доступен на всех уровнях отношений»
(make the token-priced cosplay photoshoot available at ALL relationship levels,
not only from level 3).

The single source of truth is ``SCENE_LEVELS['cosplay']`` in
services/photo_service.py — it drives BOTH the backend gate
(``scene_allowed_for_stage``) and the photo-menu button visibility
(``photo_keyboard``: ``level >= SCENE_LEVELS.get('cosplay', ...)``). Setting it
to 1 (the floor) unlocks cosplay everywhere, while the 18+ confirmation and the
token price stay intact.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.31.4', '3.31.5', '3.31.6', '3.31.7', '3.31.8', '3.32.0', '3.32.1', '3.33.0', '3.33.1')


def test_cosplay_scene_level_is_floor():
    # the gate value dropped from 3 to 1 (level 1 = available to everyone)
    assert "'cosplay': 1," in PHOTO
    assert "'cosplay': 3," not in PHOTO
    # ... and it lives inside SCENE_LEVELS
    block = PHOTO[PHOTO.index('SCENE_LEVELS = {'):PHOTO.index('def scene_allowed_for_stage')]
    assert "'cosplay': 1," in block


def test_backend_gate_reads_scene_levels():
    # scene_allowed_for_stage compares the stage against SCENE_LEVELS, so a
    # cosplay value of 1 makes it pass at the very first relationship stage.
    assert 'def scene_allowed_for_stage(scene: str, stage: str) -> bool:' in PHOTO
    assert 'return STAGE_INDEX.get(stage, 0) + 1 >= SCENE_LEVELS.get(scene, 99)' in PHOTO


def test_photo_menu_button_unlocked_at_every_level():
    kb = MAIN[MAIN.index('def photo_keyboard(telegram_id: int):'):]
    kb = kb[:kb.index('return InlineKeyboardMarkup(inline_keyboard=rows)')]
    # the cosplay button gate now defaults to the floor (level 1)
    assert "if level >= SCENE_LEVELS.get('cosplay', 1):" in kb
    assert "callback_data='cosplay:start'" in kb
    assert '🎭 Косплей-фотосет' in kb


def test_cosplay_still_gated_by_adult_and_tokens():
    # removing the LEVEL gate must NOT remove the 18+ / token-price guards
    block = MAIN[MAIN.index("@dp.callback_query(F.data == 'cosplay:start')"):]
    block = block[:block.index("@dp.callback_query(F.data.startswith('walletpay:'))")]
    assert 'if not has_accepted(cq.from_user.id):' in block
    assert 'spend_tokens(cq.from_user.id, COSPLAY_TOKEN_COST)' in block
    assert "PhotoRequest(scene='cosplay', clothing=costume[1], hairstyle=costume[2], hair_color=costume[3])" in block
