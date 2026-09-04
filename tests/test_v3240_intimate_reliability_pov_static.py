"""V3.24.0 static pins: intimate photo reliability, constructor admin fix, POV video presets.

Covers:
1. Seedream runs every intimate scene with fal's safety checker disabled
   (SEEDREAM_ADULT_SCENES) so lingerie/boudoir sets no longer die on fal 4xx
   and then on the Gemini http_400 fallback.
2. Fallback-chain errors name every failed engine in order, so the owner sees
   which engine failed FIRST (e.g. missing FAL_KEY) instead of only the tail.
3. The constructor admin free path passes the real user id into
   _finish_constructor — cq.message.from_user is the BOT there.
4. hug/kiss video presets are POV: the camera is the viewer's eyes, she hugs
   and kisses the viewer, never herself.
"""
from __future__ import annotations

import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.24.0', '3.25.0', '3.26.0', '3.26.1', '3.30.0', '3.30.1', '3.30.2', '3.30.3', '3.30.4')


def test_seedream_adult_scenes_cover_all_intimate_sets():
    photo = importlib.import_module('services.photo_service')
    assert {'personal', 'lingerie', 'private_fashion', 'nude', 'tease'} <= photo.SEEDREAM_ADULT_SCENES
    # the Seedream set runner disables fal's safety checker for those scenes
    assert 'allow_adult = request.scene in SEEDREAM_ADULT_SCENES' in PHOTO
    # hybrid routing sends the same scenes to Seedream
    assert 'request.scene in SEEDREAM_ADULT_SCENES or INTIMATE_STYLE.search' in PHOTO


def test_fallback_chain_error_names_every_failed_engine():
    assert "chain = [f'seedream45/{exc.reason}']" in PHOTO
    assert "chain.append(f'gemini_image/{gemini_exc.reason}')" in PHOTO
    assert "chain.append(f'openai/{openai_exc.reason}')" in PHOTO
    assert "' → '.join(chain)" in PHOTO


def test_constructor_admin_path_uses_real_user_id():
    assert 'async def _finish_constructor(message: types.Message, charge: str | None, telegram_id: int | None = None):' in MAIN
    assert 'telegram_id = telegram_id if telegram_id is not None else message.from_user.id' in MAIN
    # v3.28.0: constructor spawns are tracked through _spawn_job
    assert "_spawn_job('constructor', telegram_id, _finish_constructor(cq.message, None, telegram_id)" in MAIN
    # the paid path still works with the default (payment message from_user)
    assert "_spawn_job('constructor', message.from_user.id, _finish_constructor(message, charge)" in MAIN


def test_video_presets_are_pov_not_self_hug():
    cloud_video = importlib.import_module('services.cloud_video_service')
    # V3.26.0: the artifact-prone hug/dance presets are gone; kiss/whisper/touch
    # keep the POV framing pinned in v3.24.0.
    assert 'hug' not in cloud_video.VIDEO_PRESETS
    assert 'dance' not in cloud_video.VIDEO_PRESETS
    kiss_prompt = cloud_video.VIDEO_PRESETS['kiss'][1]
    whisper_prompt = cloud_video.VIDEO_PRESETS['whisper'][1]
    touch_prompt = cloud_video.VIDEO_PRESETS['touch'][1]
    for prompt in (kiss_prompt, whisper_prompt, touch_prompt):
        assert "viewer's eyes" in prompt
        assert 'Preserve her identity' in prompt
        assert 'No wardrobe change' in prompt
        assert 'no extra people' in prompt
