"""V3.43.6 static pins: the figure finally stops drifting — for everyone.

The owner's escalation (after v3.43.5 did not cure it): «сделай, чтобы все
персонажи у них грудь не плавала, фигура не плавала… она стоит на экране с
грудью пятого размера, генерирует в чате вообще грудь второго размера».

The real root cause sat BELOW the BODY IDENTITY declaration: every engine's
closing instruction told the model to take the physique FROM THE REFERENCE
PHOTOS. Gemini (the primary route for ordinary scenes) ended each prompt
with «Keep the same fictional adult person, same exact face and overall
physique»; the OpenAI safe/compatibility retries and the Seedream
frame-trailer carried the same pull; and the non-Anna preserve list itself
contained phrases like Emily's «fit feminine physique» injected straight
into «Preserve these exact traits from the canonical references». A
reference photo with a smaller bust beat the declared figure every frame.

V3.43.6 re-routes the reference channel to the FACE only:
1. every engine trailer now says the references anchor face and hair, while
   the body follows the BODY IDENTITY declaration — even when a reference
   shows a smaller or different build;
2. the non-Anna identity block gains an explicit REFERENCE PROTOCOL scoping
   references to face/hair/coloring, body exclusively from the declaration;
3. BUST CONSISTENCY (already injected into every prompt) now states it
   OVERRIDES any smaller or flatter bust visible in the references;
4. the heroine JSON anchors declare the house bust size outright — Emily's
   «fit feminine physique» and Maria's «gentle curvy feminine proportions»
   are gone, all seven non-Anna heroines name size 5, E cup.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO_SVC = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.44.4', '3.44.3', '3.43.7', '3.43.6')


# ── 1. the engine trailers no longer pull the body from references ──────────

def test_gemini_trailer_scopes_references_to_face():
    # the primary ordinary-scene route: the trailer used to close every
    # prompt with «same exact face and overall physique» — a direct order
    # to copy the reference's (smaller) bust over the declared figure.
    assert 'NANO BANANA ORDINARY-PHOTO RULE: Use the supplied canonical references as FACE and HAIR identity anchors only.' in PHOTO_SVC
    assert "The character's body and figure follow the BODY IDENTITY declaration in this prompt — including the declared bust size — even when a reference photo shows a smaller or different build." in PHOTO_SVC
    assert 'same exact face and overall physique' not in PHOTO_SVC


def test_openai_retry_lines_scope_references_to_face():
    # the safe retry used to demand «canonical body proportions from the
    # references»; the single-reference retry demanded the «stable overall
    # silhouette» — both fed the drift.
    assert 'Preserve the exact face from the references; the body follows the BODY IDENTITY declaration, never the references; safety changes styling, not identity.' in PHOTO_SVC
    assert 'canonical body proportions from the references' not in PHOTO_SVC
    assert 'her body follows the BODY IDENTITY declaration, never the reference silhouette.' in PHOTO_SVC
    assert 'stable overall silhouette' not in PHOTO_SVC


def test_seedream_trailer_defers_to_the_declaration():
    # the frame trailer used to say «face identity and body proportions as
    # the other photos in this set» — frame 1 had nothing to anchor on, and
    # the edit-mode reference supplied the body instead.
    assert 'her body always follows the declared BODY IDENTITY — never the reference silhouette.' in PHOTO_SVC
    assert 'face identity and body proportions as the other photos' not in PHOTO_SVC


# ── 2. the non-Anna identity block scopes the references explicitly ─────────

def test_non_anna_identity_carries_reference_protocol():
    assert "f'REFERENCE PROTOCOL: the canonical reference images define {name}\\'s face, hairstyle, '" in PHOTO_SVC
    assert "'coloring and recognizable identity ONLY; her body measurements, bust size and figure '" in PHOTO_SVC
    assert "'come exclusively from the BODY IDENTITY declaration, never from the reference photos. '" in PHOTO_SVC
    # the protocol rides inside the identity, right after the preserve list
    assert "f'{reference_protocol}'" in PHOTO_SVC


def test_bust_consistency_rule_overrides_references():
    # BUST CONSISTENCY is injected into every prompt unconditionally —
    # now it states the override explicitly.
    assert "'This bust size is a permanent identity trait and OVERRIDES any smaller or flatter bust visible in the reference photos.'" in PHOTO_SVC


# ── 3. the heroine JSON anchors declare the house bust size ─────────────────

HEROINE_BUST_ANCHOR = 'silicone, Russian size 5, E cup'


def test_every_heroine_json_declares_the_house_bust():
    for cid in ('alena_01', 'maria_01', 'erika_01', 'sonya_01', 'vika_01', 'alisa_01', 'mila_01'):
        profile = json.loads((ROOT / 'data' / 'characters' / f'{cid}.json').read_text(encoding='utf-8'))
        anchors = ' '.join(profile['visual_identity']['preserve_identity'])
        assert HEROINE_BUST_ANCHOR in anchors, cid


def test_contradictory_weak_anchors_are_gone():
    alena = json.loads((ROOT / 'data' / 'characters' / 'alena_01.json').read_text(encoding='utf-8'))
    assert 'fit feminine physique' not in ' '.join(alena['visual_identity']['preserve_identity'])
    maria = json.loads((ROOT / 'data' / 'characters' / 'maria_01.json').read_text(encoding='utf-8'))
    assert 'gentle curvy feminine proportions' not in ' '.join(maria['visual_identity']['preserve_identity'])


def test_new_heroine_curvy_pin_survives():
    # the v3.39.0 pin: the five newer heroines keep the curvy-hourglass
    # anchor substring (the size was appended inside the same phrase).
    for cid in ('erika_01', 'sonya_01', 'vika_01', 'alisa_01', 'mila_01'):
        profile = json.loads((ROOT / 'data' / 'characters' / f'{cid}.json').read_text(encoding='utf-8'))
        anchors = ' '.join(profile['visual_identity']['preserve_identity'])
        assert 'curvy hourglass figure with a full bust' in anchors, cid
