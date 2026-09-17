"""V3.43.4 static pins: «добавь градус» — hotter boudoir presentation.

The owner asked for more heat within the established adult line (lingerie
with opaque coverage, no nudity, no explicit anatomy). This release turns
the temperature up in the three places that actually shape the frames and
the chat:

1. photo scenes — personal/lingerie/private_fashion/tease descriptors now
   name the boudoir wardrobe (lace push-up set, garter belt, sheer-top
   stockings, satin/robe styling) and warm candlelit/lamp light;
2. variety pools — UNDERWEAR_STYLE_POOL gained a boudoir half (balconette,
   garter belt, bustier, velvet plunge…) and private scenes draw poses from
   the new sultrier PRIVATE_POSE_POOL instead of the neutral POSE_POOL;
3. chat — the default flirt ceiling is bolder (dirtier innuendo allowed by
   default, her initiative first), while the no-graphic-anatomy line and
   the Anna seedream opaque-coverage safety line stay untouched.

The 'nude' scene wording is deliberately NOT touched — no nudity
amplification; the level-6 gates and the opaque-coverage line stay.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO_SVC = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
CHARACTER_SVC = (ROOT / 'services' / 'character_service.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.43.5', '3.43.4')


# ── 1. hotter private-scene descriptors ─────────────────────────────────────

def test_private_scene_descriptors_carry_boudoir_heat():
    # the legacy pin from v3.10.7 must survive the rewrite
    assert 'tasteful private adult lingerie portrait' in PHOTO_SVC
    # …and the new heat: garter belts, stockings, candlelight, sultry posing
    assert 'a sultry boudoir lace set with a garter belt and sheer-top stockings' in PHOTO_SVC
    assert 'warm candlelit bedroom light, confident seductive posing' in PHOTO_SVC
    assert 'bold adult boudoir glamour: a lace push-up set with a garter belt' in PHOTO_SVC
    assert 'a satin robe slipping off one shoulder, sultry warm low light' in PHOTO_SVC
    assert 'a sheer kimono over lace lingerie, intimate warm lamp light' in PHOTO_SVC
    assert 'back softly arched, a smirking glance over her shoulder' in PHOTO_SVC
    # every upgraded descriptor keeps the coverage line
    assert 'non-explicit and fully covered by the garment' in PHOTO_SVC
    assert 'non-explicit, with opaque lingerie coverage' in PHOTO_SVC


def test_nude_scene_wording_not_amplified():
    # the level-6 artistic-nude scene keeps its original wording — this
    # release heats the lingerie/boudoir line, not the nude tier
    assert "'nude': 'a tasteful artistic nude portrait made in privacy for someone she deeply trusts, confident and warm'" in PHOTO_SVC


# ── 2. boudoir wardrobe + posing pools ──────────────────────────────────────

def test_underwear_pool_gained_boudoir_half():
    assert 'lace push-up balconette bra and matching panties' in PHOTO_SVC
    assert 'garter belt with sheer-top stockings and a lace bra' in PHOTO_SVC
    assert 'satin bustier corset and matching panties' in PHOTO_SVC
    assert 'velvet plunge bra and high-cut panties' in PHOTO_SVC
    assert 'white bridal lace set with garters' in PHOTO_SVC
    # the everyday half survives — variety, not a total takeover
    assert 'everyday cotton bra and matching panties' in PHOTO_SVC


def test_private_scenes_use_sultrier_poses():
    assert 'PRIVATE_POSE_POOL = [' in PHOTO_SVC
    assert 'lying on her side on the bed, propped on one elbow' in PHOTO_SVC
    assert 'seated on the edge of the bed with her back softly arched' in PHOTO_SVC
    assert 'kneeling on the bed facing the camera' in PHOTO_SVC
    # the neutral pool stays for public venues
    assert 'POSE_POOL = [' in PHOTO_SVC
    # and the branch that routes private scenes to the boudoir pool
    assert "poses = list(PRIVATE_POSE_POOL if request.scene in {'personal', 'lingerie', 'private_fashion', 'tease'} else POSE_POOL)" in PHOTO_SVC


def test_scene_tiers_got_boudoir_texture():
    # suggestive/revealing tiers now name garters/stockings and warm light
    assert 'a garter belt and sheer-top stockings with the lace set clearly visible, warm candlelit glow' in PHOTO_SVC
    assert 'the lace push-up set with garter belt and stockings IS the outfit, sultry warm lamp light' in PHOTO_SVC
    assert 'her lace set with stockings clearly visible, warm authentic bedroom lamp light' in PHOTO_SVC
    assert 'her lace set with stockings as the main outfit, sultry low-key lighting' in PHOTO_SVC


def test_private_captions_are_hotter():
    assert 'этот сет только для тебя 😏🔥' in PHOTO_SVC
    assert 'ощущаю себя сегодня опасной 😈' in PHOTO_SVC
    assert 'такой сет больше никому не покажу 🔥' in PHOTO_SVC
    assert 'смотри сколько хочешь, но не трогай 😈' in PHOTO_SVC


# ── 3. bolder default flirt ceiling in chat ────────────────────────────────

def test_default_flirt_block_is_bolder():
    # legacy pins survive (test_v3121 owns them too)
    assert 'Лёгкая пошлость — это нормально' in CHARACTER_SVC
    assert 'Без графического секса и анатомических деталей' in CHARACTER_SVC
    # the new default heat: dirtier innuendo + her own initiative
    assert 'Смелые грязноватые намёки — тоже норма' in CHARACTER_SVC
    assert '«если бы ты знал, что у меня на уме 😈»' in CHARACTER_SVC
    assert 'Инициатива всегда твоя: сама переводи разговор в игривое русло' in CHARACTER_SVC
