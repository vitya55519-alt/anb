"""Static regression tests for v3.16.8: hair identity + HF video hardening.

Two independent fixes:
1. All characters cycle hair color monthly (brunette, blonde, chestnut,
   caramel). The override line in the prompt is conditional — when hair_color
   is set it overrides the reference, when empty the identity controls it.
2. The HF video service gets broader parameter-name patterns, a label/type
   fallback for endpoint discovery, better error detection and schema logging.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
HF_VIDEO = (ROOT / 'services' / 'hf_video_service.py').read_text(encoding='utf-8')


# ── Hair color: all characters cycle ──────────────────────────────────────

def test_hair_color_cycle_applies_to_all_characters():
    # _resolve_request applies current_hair_color() to ALL characters.
    # The cycle was originally Anna-only but users want all characters to
    # shift hair color monthly: brunette -> blonde -> chestnut -> caramel.
    assert "current_hair_color()" in PHOTO
    # There must NOT be an Anna-only gate for the hair color cycle.
    assert "character_id == 'anna_01':" not in PHOTO[PHOTO.index('def _resolve_request'):PHOTO.index('def _shot_variant')]


def test_build_prompt_skips_hair_color_override_when_empty():
    # The "HAIR COLOR THIS MONTH" line must be conditional, not unconditional.
    # When request.hair_color is empty the override line is omitted entirely,
    # so the character's identity description controls the hair color.
    assert "if request.hair_color else ''" in PHOTO


def test_current_hair_color_still_exists():
    # The monthly cycle is preserved for all characters.
    assert 'def current_hair_color()' in PHOTO
    assert 'HAIR_COLOR_CYCLE' in PHOTO
    assert "'rich dark brunette'" in PHOTO
    assert "'natural blonde'" in PHOTO


# ── HF video hardening ───────────────────────────────────────────────────

def test_hf_video_expanded_parameter_names():
    # Broader image parameter set: covers more space variants.
    assert "'first_frame'" in HF_VIDEO
    assert "'first_frame_image'" in HF_VIDEO
    assert "'input_picture'" in HF_VIDEO
    assert "'source_img'" in HF_VIDEO
    # Broader prompt parameter set.
    assert "'description'" in HF_VIDEO
    assert "'text_prompt'" in HF_VIDEO
    assert "'input_text'" in HF_VIDEO


def test_hf_video_label_type_fallback():
    # Pass 2: when parameter names don't match, the resolver tries labels
    # and type hints so spaces with empty parameter_name still work.
    assert '_IMAGE_LABEL_HINTS' in HF_VIDEO
    assert '_PROMPT_LABEL_HINTS' in HF_VIDEO
    assert "p.get('label')" in HF_VIDEO
    assert "p.get('type')" in HF_VIDEO
    assert "'file' in ptype" in HF_VIDEO
    # The resolver logs the space schema for owner diagnostics.
    assert "HF video space schema:" in HF_VIDEO


def test_hf_video_better_error_detection():
    # _is_error_string detects when the space returns a text error.
    assert 'def _is_error_string(' in HF_VIDEO
    assert "'error'" in HF_VIDEO
    assert "'nsfw'" in HF_VIDEO
    assert "'content policy'" in HF_VIDEO
    # The blocking generator surfaces the raw result for debugging and
    # detects error strings before falling through to no_video_result.
    assert "space_error:" in HF_VIDEO
    assert "raw result=" in HF_VIDEO


def test_hf_video_extract_handles_more_result_shapes():
    # _extract_video_ref now handles pathlib.Path, dataclass-like objects
    # and additional dict keys used by newer spaces.
    assert "'video_url'" in HF_VIDEO
    assert "'output_video'" in HF_VIDEO
    assert "'__fspath__'" in HF_VIDEO
    # Dataclass / NamedTuple fallback for exotic result types.
    assert "getattr(item, attr, None)" in HF_VIDEO
