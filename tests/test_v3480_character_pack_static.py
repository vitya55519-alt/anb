"""V3.48.0 static checks: the owner-photo character pack (seven new heroines)
+ the like-badge relocation on the character page.

The seven characters (violetta/darina/eva/romina/kristina/zlata/veronika) are
built from the owner's supplied reference photos (owner explicitly approved
using them as-is). Every registration touchpoint must be present or the
heroine silently degrades to Anna's voice/texts at runtime.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NEW_IDS = [
    'violetta_01', 'darina_01', 'eva_01', 'romina_01',
    'kristina_01', 'zlata_01', 'veronika_01',
]
FOLDERS = {cid: cid.replace('_01', '') for cid in NEW_IDS}

# Pools in retention_features_service that fall back to anna_01 when a
# character is missing — every new heroine needs her own voice in all of them.
POOL_NAMES = [
    'MORNING_MESSAGES', 'EVENING_MESSAGES', 'MISS_TEXTS', 'JEALOUSY_TEXTS',
    'CLIFFHANGER_TEXTS', 'GIFT_MESSAGES', 'STORY_TEMPLATES', 'MINI_QUESTS',
    'WEEKLY_DATES',
]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')


def test_character_jsons_are_complete():
    for cid in NEW_IDS:
        data = json.loads(_read(f'data/characters/{cid}.json'))
        assert data['id'] == cid
        assert data['is_adult'] is True and data['age'] >= 18
        assert data['identity_type'] == 'fictional_ai_character'
        comm = data['personality']['communication']
        assert comm['language'] == 'auto' and comm['tone'] and comm['flirting']
        vi = data['visual_identity']
        folder = FOLDERS[cid]
        assert vi['reference_folder'] == f'data/references/{folder}'
        assert vi['openai_face_anchor'] == f'00_{folder}_canonical_face.png'
        assert vi['openai_body_anchor'] == f'01_{folder}_canonical_look.png'
        assert vi['preserve_identity'] and vi['identity_lock']
        assert data['boundaries']['no_nudity_generation'] is True


def test_canonical_reference_files_exist():
    for cid in NEW_IDS:
        folder = ROOT / 'data' / 'references' / FOLDERS[cid]
        assert (folder / f'00_{FOLDERS[cid]}_canonical_face.png').exists(), cid
        assert (folder / f'01_{FOLDERS[cid]}_canonical_look.png').exists(), cid
    # Violetta groups three owner photos — the two extra looks ride along as
    # storefront carousel shots (02_/03_ are ignored by the generation anchors).
    violetta = ROOT / 'data' / 'references' / 'violetta'
    assert (violetta / '02_violetta_reference_1.png').exists()
    assert (violetta / '03_violetta_reference_2.png').exists()


def test_cards_and_hooks_registered():
    cards = _read('services/character_card_service.py')
    for cid in NEW_IDS:
        assert f'"{cid}":' in cards, cid
    # Every new heroine opens with an intrigue-only hook — none may describe
    # her appearance in the scenario hook (owner content rule).
    hooks_block = cards.split('SCENARIO_HOOKS = {', 1)[1]
    for cid in NEW_IDS:
        hook = hooks_block.split(f'"{cid}": (', 1)[1].split('),', 1)[0]
        assert '«' in hook and '?' in hook, cid


def test_storefront_face_references_registered():
    webapp = _read('services/webapp_service.py')
    refs = webapp.split('_FACE_REFERENCES = {', 1)[1].split('\n}', 1)[0]
    for cid in NEW_IDS:
        folder = FOLDERS[cid]
        assert f"'{cid}': ('references', '{folder}', '00_{folder}_canonical_face.png')" in refs, cid


def test_pace_and_temperament_registered():
    engine = _read('services/relationship_engine.py')
    pace = engine.split('CHARACTER_PACE = {', 1)[1].split('\n}', 1)[0]
    hints = engine.split('PACE_HINTS = {', 1)[1].split('\n}', 1)[0]
    for cid in NEW_IDS:
        assert f"'{cid}':" in pace, cid
        assert f"'{cid}':" in hints, cid


def test_retention_pools_cover_every_new_heroine():
    text = _read('services/retention_features_service.py')
    for pool in POOL_NAMES:
        block = text.split(f'{pool} = {{', 1)[1].split('\n}', 1)[0]
        for cid in NEW_IDS:
            assert f"'{cid}': [" in block, f'{cid} missing in {pool}'


def test_two_caring_personas_and_veronika_age():
    # The owner asked for exactly two caring heroines (Darina + Veronika) and
    # a 36-year-old sexy/caring persona whose speech stays age-appropriate.
    darina = json.loads(_read('data/characters/darina_01.json'))
    veronika = json.loads(_read('data/characters/veronika_01.json'))
    assert 'заботливая' in darina['personality']['core']
    assert 'заботливая' in veronika['personality']['core']
    assert 'сексуальная' in veronika['personality']['core']
    assert veronika['age'] == 36
    assert 'без сленга' in veronika['personality']['communication']['tone']


def test_like_badge_moved_off_the_photo_strip():
    html = _read('webapp/index.html')
    # The badge no longer lives inside .stripwrap (it covered the 4th thumb)…
    stripwrap = html.split('<div class="stripwrap">', 1)[1].split('</div>', 1)[0]
    assert 'charlike' not in stripwrap
    # …it now sits in the hero header row next to the name.
    hero_line = next(l for l in html.splitlines() if 'class="charhero"' in l)
    assert 'id="charLike"' in hero_line
    css = html.split('.charlike {', 1)[1].split('}', 1)[0]
    assert 'top: 10px; right: 16px' in css
    # .charhero must be positioned for the absolute badge to anchor there.
    assert '.charhero { padding: 6px 16px 0; position: relative; }' in html


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('V3480_CHARACTER_PACK_STATIC_OK')
