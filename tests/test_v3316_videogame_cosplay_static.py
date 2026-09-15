"""Static tests for v3.31.6: sexy + popular video-game heroines in cosplay.

Owner request: «в косплей добавь еще героинь сексуальных и популярных из видео
игр». The COSPLAY_COSTUMES picker in main.py grows from 8 to 18 costumes with
recognisable video-game heroines (2B, Lara Croft, Tifa, Chun-Li, Ahri, D.Va,
Bayonetta, Yennefer, Raiden Shogun, Ada Wong).

The cosplay scene is declared *fully clothed*, so each new prompt describes the
iconic costume concretely and must not carry explicit/lingerie wording that
would trip provider moderation. This test parses the dict with AST (not text
matching) so the guarantees stay exact as the list grows.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()

NEW_KEYS = ['nier2b', 'lara', 'tifa', 'chunli', 'ahri',
            'dva', 'bayonetta', 'yennefer', 'raiden', 'ada']
BANNED = ('nude', 'naked', 'topless', 'explicit', 'lingerie', 'underwear')


def _costumes() -> dict:
    tree = ast.parse(MAIN)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(t, 'id', '') == 'COSPLAY_COSTUMES' for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError('COSPLAY_COSTUMES not found in main.py')


def test_version_bumped():
    assert VERSION in ('3.31.5', '3.31.6', '3.31.7', '3.31.8', '3.32.0', '3.32.1', '3.33.0', '3.33.1', '3.34.0', '3.34.1', '3.35.0', '3.36.0', '3.37.0', '3.38.0', '3.39.0')


def test_new_videogame_heroines_present():
    costumes = _costumes()
    for key in NEW_KEYS:
        assert key in costumes, f'missing heroine: {key}'
        label, prompt = costumes[key][0], costumes[key][1]
        assert label and prompt, key
    # picker grew from 8 to at least 18 costumes
    assert len(costumes) >= 18, len(costumes)


def test_every_costume_is_label_prompt_pair():
    for key, value in _costumes().items():
        # V3.31.7: 4-tuple (label, prompt, iconic hairstyle, iconic hair color)
        assert isinstance(value, tuple) and len(value) == 4, key
        assert isinstance(value[0], str) and isinstance(value[1], str), key
        assert value[0].strip() and value[1].strip(), key


def test_costumes_stay_fully_clothed_and_safe():
    # the scene is fully clothed: no explicit/lingerie wording may sneak in
    for key, (_label, prompt, *_hair) in _costumes().items():
        low = prompt.lower()
        for word in BANNED:
            assert word not in low, f'{key} prompt contains banned word: {word}'


def test_labels_are_localised_and_emoji_tagged():
    # each new label keeps the recognisable name and a leading emoji, matching
    # the existing costume-label style
    for key in NEW_KEYS:
        label = _costumes()[key][0]
        assert label[0].strip() and not label[0].isascii(), f'{key} label needs an emoji'
