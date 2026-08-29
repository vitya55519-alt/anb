"""V3.26.0 static pins: video preset refresh — close-up motion instead of
artifact-prone full-body choreography.

The owner field report: «видео ужасное» — the hug/dance presets (full-body
embrace, dance choreography) produced heavy artifacts with i2v engines from a
single frame. V3.26.0 retires hug/dance and replaces them with low-amplitude,
close-up motion that animates cleanly: wink, turn, whisper (POV), touch (POV),
caress (sensual, tasteful). Kiss is kept as-is. The preset keyboard is now
built generically from VIDEO_PRESETS.
"""
from __future__ import annotations

import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')

EXPECTED_PRESETS = {'kiss', 'wink', 'turn', 'whisper', 'touch', 'caress'}


def _cloud_video():
    return importlib.import_module('services.cloud_video_service')


def test_version_bumped():
    assert VERSION == '3.26.0'


def test_preset_set_refreshed():
    cloud_video = _cloud_video()
    assert set(cloud_video.VIDEO_PRESETS) == EXPECTED_PRESETS
    # The artifact-prone presets must not come back.
    assert 'hug' not in cloud_video.VIDEO_PRESETS
    assert 'dance' not in cloud_video.VIDEO_PRESETS
    # Kiss is the one the owner asked to keep.
    assert 'kiss' in cloud_video.VIDEO_PRESETS


def test_every_preset_locks_identity_and_wardrobe():
    cloud_video = _cloud_video()
    for key, (label, prompt) in cloud_video.VIDEO_PRESETS.items():
        assert label, f'{key} must have a button label'
        assert 'Animate this exact photo' in prompt, f'{key} must anchor the photo'
        assert 'Preserve her identity' in prompt, f'{key} must lock identity'
        assert 'No wardrobe change' in prompt, f'{key} must lock wardrobe'
        assert 'no extra people' in prompt, f'{key} must forbid extra people'


def test_pov_presets_frame_camera_as_viewer():
    cloud_video = _cloud_video()
    for key in ('kiss', 'whisper', 'touch'):
        prompt = cloud_video.VIDEO_PRESETS[key][1]
        assert "viewer's eyes" in prompt, f'{key} must keep the POV framing'


def test_caress_stays_tasteful():
    cloud_video = _cloud_video()
    prompt = cloud_video.VIDEO_PRESETS['caress'][1]
    # The sensual preset deliberately keeps the engine safety line so video
    # moderation does not reject it — no explicit sexual action.
    assert 'no sexual action' in prompt
    assert 'above her heart' in prompt


def test_keyboard_built_generically_from_presets():
    block = MAIN[MAIN.index('def _video_preset_keyboard'):MAIN.index('async def _show_video_preset_menu')]
    # Generic construction: no hardcoded preset keys, one Авто button.
    assert "keys = list(VIDEO_PRESETS)" in block
    assert "callback_data=f'videopreset:{key}:{delivery_id}'" in block
    assert 'videopreset:auto' in block
    assert "VIDEO_PRESETS['hug']" not in MAIN
    assert "VIDEO_PRESETS['dance']" not in MAIN
