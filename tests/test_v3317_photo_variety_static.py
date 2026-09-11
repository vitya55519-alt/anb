"""Static regression tests for v3.31.7: photo variety + single hairstyle.

Owner complaint: «фото с косяками, прическа на прическе, и на фотках одна и
та же мимика и все одно и тоже» — cosplay photos showed TWO hairstyles stacked
(the random pool hairstyle plus the braid named inside the costume prompt), and
every frame repeated the same facial expression and the same posture.

Pinned fixes:
1. COSPLAY_COSTUMES values are 4-tuples (label, prompt, iconic hair, hair
   color); heroine prompts no longer mention hair at all, and cosplay_pick
   sends the iconic hair via PhotoRequest.hairstyle/hair_color so exactly ONE
   hairstyle reaches the prompt.
2. The HAIRSTYLE prompt line declares exclusivity (no second hairdo).
3. A per-frame expression rotation (new laughing/confident/thoughtful/shy
   keys) and per-frame POSE_POOL notes replace the fixed warm smile and the
   repeated posture.
4. The Gemini route no longer freezes the reference hair color/style and the
   warm smile — identity is face + physique only.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
EXPR = (ROOT / 'services' / 'photo_expression_service.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()

HEROINES = ['nier2b', 'lara', 'tifa', 'chunli', 'ahri',
            'dva', 'bayonetta', 'yennefer', 'raiden', 'ada']
CLASSICS = ['maid', 'nurse', 'cat', 'bunny', 'elf', 'witch', 'superhero', 'police']
HAIR_WORDS = ('braid', 'ponytail', 'hair', 'fringe', 'bob')


def _costumes() -> dict:
    tree = ast.parse(MAIN)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(t, 'id', '') == 'COSPLAY_COSTUMES' for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError('COSPLAY_COSTUMES not found in main.py')


def test_version_bumped():
    assert VERSION in ('3.31.6', '3.31.7')


def test_costumes_carry_iconic_hair_fields():
    costumes = _costumes()
    for key in HEROINES:
        _label, prompt, hair, color = costumes[key]
        assert hair.strip(), f'{key} must pin an iconic hairstyle'
        assert color.strip(), f'{key} must pin an iconic hair color'
        # the costume prompt itself must not talk about hair — otherwise the
        # model stacks it on top of the HAIRSTYLE line ("прическа на прическе")
        low = prompt.lower()
        for word in HAIR_WORDS:
            assert word not in low, f'{key} prompt still mentions hair: {word}'
    for key in CLASSICS:
        _label, _prompt, hair, color = costumes[key]
        assert hair == '' and color == '', f'{key} must keep the generic pools'


def test_cosplay_pick_sends_hair_in_request():
    assert ("PhotoRequest(scene='cosplay', clothing=costume[1], "
            'hairstyle=costume[2], hair_color=costume[3])') in MAIN


def test_hairstyle_line_is_exclusive():
    assert 'This is her one and only hairstyle in the frame' in PHOTO
    assert 'never combine it with a second hairdo, extra braid, bun, wig or hairpiece' in PHOTO


def test_expression_rotation_pool_extended():
    for key in ('laughing', 'confident', 'thoughtful', 'shy'):
        assert f"'{key}': (" in EXPR, f'missing expression: {key}'
    assert 'VARIETY_KEYS' in EXPR
    assert 'def shuffled_variety_keys() -> tuple[str, ...]:' in EXPR


def test_photo_request_and_prompt_use_rotations():
    assert 'expression_rotation: tuple[str, ...] = ()' in PHOTO
    assert 'pose_rotation: tuple[str, ...] = ()' in PHOTO
    assert 'POSE_POOL = [' in PHOTO
    assert 'shuffled_variety_keys()' in PHOTO
    # per-frame picks inside _build_prompt
    assert 'request.expression_rotation[shot_index % len(request.expression_rotation)]' in PHOTO
    assert 'POSE NOTE: {request.pose_rotation[shot_index % len(request.pose_rotation)]}' in PHOTO
    # _resolve_request fills both rotations on the resolved request
    resolve = PHOTO[PHOTO.index('def _resolve_request('):PHOTO.index('def _shot_variant(')]
    assert 'expression_rotation=expression_rotation, pose_rotation=pose_rotation' in resolve


def test_gemini_rule_no_longer_freezes_hair_and_smile():
    assert ('same exact face, hair color and style, overall physique '
            'and subtle warm smile') not in PHOTO
    assert ('follow the requested HAIR COLOR, HAIRSTYLE, EXPRESSION and WARDROBE lines, '
            'not the reference photos') in PHOTO
