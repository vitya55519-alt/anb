"""Static regression test for v3.19.12: video motion preset buttons.

The preset keyboard (kiss/hug/dance/auto) looked dead because the callback
handler unpacked 'videopreset:<preset>:<id>' as preset='videopreset', which
failed the VIDEO_PRESETS membership check and silently returned. The unpack
must skip the router prefix so the chosen motion prompt reaches the engine.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_preset_callback_skips_router_prefix():
    block = MAIN[MAIN.index("@dp.callback_query(F.data.startswith('videopreset:'))"):MAIN.index('async def _video_gate')]
    # Correct unpack: prefix first, preset second.
    assert '_, preset, raw_id = parts' in block
    # The old buggy unpack must never come back.
    assert 'preset, _, raw_id = parts' not in block


def test_preset_reaches_animation_job():
    block = MAIN[MAIN.index("@dp.callback_query(F.data.startswith('videopreset:'))"):MAIN.index('async def _video_gate')]
    # 'auto' means no preset (scene-aware default); a chosen preset rides along.
    assert "await _video_gate(cq, delivery, preset if preset != 'auto' else None)" in block


def test_presets_carry_motion_prompts():
    from services.cloud_video_service import VIDEO_PRESETS
    assert set(VIDEO_PRESETS) == {'kiss', 'hug', 'dance'}
    for label, prompt in VIDEO_PRESETS.values():
        assert label and 'Animate this exact photo' in prompt
        assert 'No wardrobe change, no extra people' in prompt
