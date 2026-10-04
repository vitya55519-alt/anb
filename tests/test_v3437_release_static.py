"""V3.43.7 static pins: the app-chat photo finally generates through the
REAL pipeline — and the scene menus come back.

Owner escalation after v3.43.6: «это не поменялось, ничего не изменилось»
plus «когда я на фото нажимаю в приложении, раньше я мог выбирать где —
фэшен не фэшен, парк, дом, улица — сейчас этого нет, добавь это обратно».

Why v3.43.6 "did nothing" for the app: the Mini App chat photo button never
ran the identity locks at all. `_webapp_media_photo` built a one-line prompt
and pushed it through `generate_custom_avatar` anchored to `gallery[0]` — a
face close-up — so the body was improvised by the face-swap engine on every
tap. The v3.43.5/v3.43.6 prompt surgery lived in `_build_prompt`, which this
path never called. The same bypass powered the V3.41.0 date reward shot.

V3.43.7:
1. `_webapp_pipeline_photo`: the app's in-character photos now run
   `generate_photo_set` (BODY IDENTITY / REFERENCE PROTOCOL / BUST
   CONSISTENCY included), one frame (`frames=1` threaded through the whole
   route chain), bytes captured for the app media folder;
2. `photo_frame_bytes` downloads URL-only providers once (bot gallery parity);
3. the photo button opens a scene picker — `/webapp/api/feature?kind=photo`
   returns PHOTO_MENU_ORDER gated by SCENE_LEVELS, the sheet renders it in
   all 7 interface languages, the chosen scene rides the media request;
4. the endpoint enforces the bot's gates: menu-scene whitelist, relationship
   stage, the 18+ adult confirmation, and the scene-flavored AUTO_CAPTIONS.
"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO_SVC = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()

CHAT_MEDIA = MAIN[MAIN.index('async def _webapp_api_chat_media('):MAIN.index('async def _webapp_media(')]
FEATURE = MAIN[MAIN.index('async def _webapp_api_feature('):MAIN.index('async def _webapp_api_feature_action(')]


def test_version_bumped():
    assert VERSION in ('3.44.4', '3.44.3', '3.43.7')


# ── 1. the app photo runs the real identity-locked pipeline ─────────────

def test_webapp_photo_uses_real_pipeline():
    assert 'async def _webapp_pipeline_photo(telegram_id: int, character_id: str, request: PhotoRequest):' in MAIN
    pipe = MAIN[MAIN.index('async def _webapp_pipeline_photo('):MAIN.index('async def _webapp_media_circle(')]
    assert 'await generate_photo_set(telegram_id, request, character_id=character_id, frames=1)' in pipe
    assert 'await photo_frame_bytes(photos[0])' in pipe
    # one frame, not a full 3-photo set: the app chat shows a single shot
    assert 'frames=1' in pipe


def test_old_bypass_is_gone():
    # the V3.39.0 shortcut (one-line prompt + face-swap on gallery[0]) is
    # deleted — it bypassed every identity lock, which is exactly why the
    # figure kept drifting in the app while the bot stayed on-spec
    assert '_WEBAPP_PHOTO_SCENES' not in MAIN
    assert 'generate_custom_avatar(prompt, reference)' not in MAIN
    # the freeform «Картинки» studio keeps its own (reference-free) engine
    assert 'generate_custom_avatar(final_prompt, None)' in MAIN


def test_date_reward_photo_also_pipelined():
    scene_fn = MAIN[MAIN.index('async def _webapp_media_scene('):MAIN.index('async def _webapp_api_chat_media(')]
    assert 'await _webapp_pipeline_photo(' in scene_fn
    assert "PhotoRequest(scene=scene, mood='romantic')" in scene_fn


def test_photo_frame_bytes_helper():
    # URL-only providers (openai/seedream) get downloaded once — the same
    # capture the bot's gallery performs in _send_frame
    assert 'async def photo_frame_bytes(photo: GeneratedPhoto) -> bytes | None:' in PHOTO_SVC
    assert 'return photo.data or (await _download_result_bytes(photo))' in PHOTO_SVC


def test_frames_parameter_threaded_through_every_engine():
    for fn in ('_run_gemini_set', '_run_openai_set', '_run_seedream_set',
               '_run_routed_photo_set', 'generate_photo_set'):
        assert f'async def {fn}(' in PHOTO_SVC
    # every set-runner accepts the frame count and the router threads it
    # into all of its branches and fallbacks
    assert PHOTO_SVC.count('frames: int = PHOTO_SET_SIZE') == 5
    assert 'frames=frames' in PHOTO_SVC


# ── 2. the scene picker: backend menu + frontend sheet ──────────────────

def test_feature_endpoint_serves_the_photo_menu():
    assert "if kind not in ('apartment', 'date', 'quest', 'photo'):" in FEATURE
    assert '} for scene in PHOTO_MENU_ORDER]' in FEATURE
    assert "'locked': SCENE_LEVELS.get(scene, 99) > level," in FEATURE
    assert "'min_level': SCENE_LEVELS.get(scene, 99)," in FEATURE


def test_chat_media_accepts_and_gates_the_scene():
    assert "scene = str(body.get('scene') or 'selfie')[:40]" in CHAT_MEDIA
    # menu-scene whitelist, relationship-stage gate, the 18+ adult gate —
    # the same rules the bot's photo keyboard enforces
    assert 'if scene not in PHOTO_MENU_ORDER:' in CHAT_MEDIA
    assert 'scene_allowed_for_stage(scene, get_relationship_stage(telegram_id, character_id))' in CHAT_MEDIA
    assert "requires_adult_confirmation(PhotoRequest(scene=scene)) and not is_adult_confirmed(telegram_id)" in CHAT_MEDIA
    assert "'error': 'adult_confirm'" in CHAT_MEDIA
    assert 'await _webapp_media_photo(telegram_id, character_id, scene)' in CHAT_MEDIA
    # her caption is scene-flavored, like the bot's delivery
    assert 'random.choice(AUTO_CAPTIONS.get(scene' in CHAT_MEDIA


def test_frontend_photo_button_opens_the_scene_menu():
    assert "getElementById('mediaPhoto').addEventListener('click', () => openFeature('photo'))" in INDEX
    assert 'const SCENE_GROUPS = [' in INDEX
    assert 'function renderPhotoScenes(j) {' in INDEX
    assert "if (j.kind === 'photo') { renderPhotoScenes(j); return; }" in INDEX
    # the four groups mirror the bot keyboard's progression
    for key in ('everyday', 'fashion', 'evening', 'private'):
        assert f"key: '{key}'" in INDEX
    # tapping a scene closes the sheet and requests that scene
    assert "requestMedia('photo', el.dataset.scene)" in INDEX
    assert 'function requestMedia(kind, scene)' in INDEX
    assert "body: JSON.stringify({ character_id: CHAT.id, kind: kind, scene: scene || '' })" in INDEX
    # the 18+ gate is explained in the user's language
    assert "j.error === 'adult_confirm' ? L.adult_confirm_needed" in INDEX
    assert '.featgroup {' in INDEX


def test_scene_menu_is_localized_in_all_seven_languages():
    # every dictionary (EN base, RU, es/it/fr/zh/ja overrides) carries the
    # picker chrome + scene labels, so nothing falls back mid-menu
    for fragment in (
        "photo_menu_title: '📸 Which photo?'",
        "photo_menu_title: '📸 Какое фото?'",
        "photo_menu_title: '📸 ¿Qué foto?'",
        "photo_menu_title: '📸 Quale foto?'",
        "photo_menu_title: '📸 Quelle photo ?'",
        "photo_menu_title: '📸 想要哪种照片？'",
        "photo_menu_title: '📸 どの写真にする？'",
    ):
        assert fragment in INDEX, f'missing picker title: {fragment}'
    for key in ('photo_menu_title:', 'sc_locked:', 'scg_everyday:',
                'sc_selfie:', 'sc_personal:', 'sc_private_fashion:',
                'adult_confirm_needed:'):
        assert INDEX.count(key) == 7, f'{key} must exist in all 7 dictionaries'


def test_scene_menu_markup_is_escaped():
    # built with string concatenation + esc() — no raw template interpolation
    # inside the new renderer (the V3.33.0 unescaped-template guard)
    block = INDEX[INDEX.index('function renderPhotoScenes('):INDEX.index('function renderFeature(')]
    assert '${' not in block
    assert "esc(typeof L['sc_' + id] === 'string' ? L['sc_' + id] : id)" in block


def _app_photo_namespace():
    """Execute the actual app helpers with mocked I/O, without starting the bot."""
    names = {'_webapp_pipeline_photo', '_webapp_media_photo', '_webapp_media_scene'}
    helpers = [node for node in ast.parse(MAIN).body
               if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
    assert {node.name for node in helpers} == names
    ns = {
        'PhotoRequest': SimpleNamespace,
        'PhotoGenerationError': RuntimeError,
        'bot': object(),
        'is_custom_character': Mock(return_value=False),
        'ensure_custom_avatar_cached': AsyncMock(),
        'generate_photo_set': AsyncMock(return_value=([object()], None)),
        'photo_frame_bytes': AsyncMock(return_value=b'\x89PNG\r\n\x1a\nframe'),
    }
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(ROOT / 'main.py'), 'exec'), ns)
    return ns


@pytest.mark.parametrize('custom', [False, True])
def test_app_photo_prepares_custom_reference_before_generation(custom):
    ns = _app_photo_namespace()
    ns['is_custom_character'].return_value = custom
    character_id = 'custom_42' if custom else 'alena_01'
    frame = object()

    async def generate(telegram_id, request, *, character_id, frames):
        assert telegram_id == 42
        assert request.scene == 'park'
        assert frames == 1
        if custom:
            ns['ensure_custom_avatar_cached'].assert_awaited_once_with(ns['bot'], character_id)
        else:
            ns['ensure_custom_avatar_cached'].assert_not_awaited()
        return [frame], request

    ns['generate_photo_set'] = AsyncMock(side_effect=generate)
    result = asyncio.run(ns['_webapp_media_photo'](42, character_id, 'park'))
    ns['is_custom_character'].assert_called_once_with(character_id)
    ns['generate_photo_set'].assert_awaited_once()
    assert ns['generate_photo_set'].await_args.kwargs['character_id'] == character_id
    ns['photo_frame_bytes'].assert_awaited_once_with(frame)
    assert result == (b'\x89PNG\r\n\x1a\nframe', 'image/png', 'png')


@pytest.mark.parametrize('scene', [
    'cafe', 'park', 'cinema', 'embankment', 'restaurant', 'rooftop', 'club', 'evening',
])
def test_date_reward_preserves_scene_through_shared_pipeline(scene):
    ns = _app_photo_namespace()
    asyncio.run(ns['_webapp_media_scene'](42, 'alena_01', scene))
    ns['generate_photo_set'].assert_awaited_once()
    call = ns['generate_photo_set'].await_args
    assert call.args[0] == 42
    assert call.args[1].scene == scene
    assert call.args[1].mood == 'romantic'
    assert call.kwargs == {'character_id': 'alena_01', 'frames': 1}
