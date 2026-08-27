"""Static regression tests for v3.16.4: reliable video generation with engine
fallback, richer looks (hairstyles/makeup/monthly hair color), bust stability,
visible-under-clothes lingerie progression and automatic contest Premium.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
HF_VIDEO = (ROOT / 'services' / 'hf_video_service.py').read_text(encoding='utf-8')
REFERRAL = (ROOT / 'services' / 'referral_service.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')


def test_unified_video_job_with_engine_fallback():
    sig = 'async def _run_video_background(chat_id: int, telegram_id: int, delivery_id: int, charge_id: str | None = None, motion_preset: str | None = None)'
    assert sig in MAIN
    block = MAIN[MAIN.index(sig):]
    block = block.split('\n\n\n@dp.', 1)[0]
    assert 'replicate_available()' in block
    assert 'hf_video_available()' in block
    assert 'animate_image_hf' in block
    assert 'if charge_id:' in block
    # The two old single-engine jobs are gone.
    assert 'async def _run_gemini_video_background(' not in MAIN
    assert 'async def _run_hf_video_background(' not in MAIN


def test_hf_service_walks_fallback_spaces():
    assert 'HF_VIDEO_FALLBACK_SPACES' in HF_VIDEO
    assert 'spaces = [HF_VIDEO_SPACE]' in HF_VIDEO
    assert 'def _generate_blocking(image_path: str, prompt: str, space: str' in HF_VIDEO
    assert 'HF_VIDEO_FALLBACK_SPACES' in CONFIG


def test_admin_video_test_command():
    block = MAIN[MAIN.index("Command('videotest')"):]
    block = block.split('\n\n\n', 1)[0]
    assert 'ADMIN_TELEGRAM_IDS' in block
    assert '_run_video_background(' in block
    assert 'get_latest_photo_delivery(' in block


def test_hairstyle_and_makeup_pools():
    pool = PHOTO[PHOTO.index('HAIRSTYLE_POOL = ['):PHOTO.index(']\n\nMAKEUP_POOL')]
    assert pool.count("'") // 2 >= 10  # at least 10 distinct hairstyles
    assert 'MAKEUP_POOL' in PHOTO
    makeup = PHOTO[PHOTO.index('MAKEUP_POOL = ['):PHOTO.index(']\n\n# Anna re-dyes')]
    assert makeup.count("'") // 2 >= 10


def test_monthly_hair_color_cycle():
    assert 'HAIR_COLOR_CYCLE' in PHOTO
    assert 'rich dark brunette' in PHOTO
    assert 'natural blonde' in PHOTO
    assert 'def current_hair_color()' in PHOTO
    assert 'HAIR COLOR THIS MONTH' in PHOTO
    assert 'overrides the hair color in the reference photos' in PHOTO


def test_outfit_color_diversity_without_orange():
    pool = PHOTO[PHOTO.index('OUTFIT_COLOR_POOL = ['):PHOTO.index(']', PHOTO.index('OUTFIT_COLOR_POOL = ['))]
    assert 'orange' not in pool.lower()
    assert pool.count("'") // 2 >= 10
    # Favorite color may appear at most once per set and never as orange.
    assert "'orange' not in favorite_color.lower()" in PHOTO
    assert 'i == 0' in PHOTO


def test_lingerie_underlay_progression_rules():
    assert 'LEVEL_UNDERLAY_RULES' in PHOTO
    rules = PHOTO[PHOTO.index('LEVEL_UNDERLAY_RULES = {'):]
    rules = rules.split('}\n\n# Bust size', 1)[0]
    assert 'only her natural feminine silhouette reads through the fitted fabric' in rules
    assert 'lace edge' in rules
    assert 'UNDER-CLOTHING REALISM' in PHOTO


def test_bust_consistency_in_every_prompt():
    assert 'BUST_CONSISTENCY_RULE' in PHOTO
    assert 'neither larger nor smaller' in PHOTO
    build = PHOTO[PHOTO.index('def _build_prompt('):]
    build = build.split('\ndef _extract_openai_many', 1)[0]
    assert 'BUST_CONSISTENCY_RULE' in build
    assert 'MAKEUP: {request.makeup}' in build


def test_contest_settles_premium_automatically():
    assert 'def settle_monthly_contest(' in REFERRAL
    assert 'contest_settled' in REFERRAL
    assert 'grant_premium(telegram_id, days=premium_days)' in REFERRAL
    assert 'settle_monthly_contest()' in MAIN
