"""Static regression tests for v3.16.5: premium-character (Maria) dialogue fix,
lingerie framed as tasteful sexuality, bigger hairstyle pool, Gemini video
auto-enabled by default, admin video diagnostics and photo-set variety
(accessories + rotating time of day)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')


def test_premium_character_selectable_by_premium_and_admin():
    # Onboarding gate: admins and premium users bypass the paywall.
    block = MAIN[MAIN.index("async def onboarding_character_select("):]
    block = block.split('\n\n\n@dp.', 1)[0]
    assert 'is_admin = cq.from_user.id in ADMIN_TELEGRAM_IDS' in block
    assert "not is_admin and not is_premium(cq.from_user.id)" in block
    # Card view: premium characters must actually get selected (this branch was
    # missing before and silently left the user chatting with the default girl).
    view = MAIN[MAIN.index("async def character_view("):]
    view = view.split('\n\n\n', 1)[0]
    assert "card.status == 'premium' and (is_admin or is_premium(cq.from_user.id))" in view
    assert "track_event(uid, 'character_selected'" in view


def test_maria_profile_and_references_exist():
    profile = json.loads((ROOT / 'data' / 'characters' / 'maria_01.json').read_text(encoding='utf-8'))
    assert profile['id'] == 'maria_01'
    assert profile.get('is_adult') is True
    folder = ROOT / profile['visual_identity']['reference_folder']
    face = folder / profile['visual_identity']['openai_face_anchor']
    body = folder / profile['visual_identity']['openai_body_anchor']
    assert face.exists(), f'missing reference {face}'
    assert body.exists(), f'missing reference {body}'
    assert (ROOT / 'data' / 'characters' / 'maria_01_dna.json').exists()


def test_lingerie_underlines_sexuality_not_objectification():
    # The framing comment above the dict carries the anti-objectification rule.
    comment = PHOTO[PHOTO.index('# How the underwear under her clothes reads'):PHOTO.index('LEVEL_UNDERLAY_RULES = {')]
    assert 'never to objectify her' in comment
    rules = PHOTO[PHOTO.index('LEVEL_UNDERLAY_RULES = {'):]
    rules = rules.split('}\n\n# Bust size', 1)[0]
    assert 'natural sexuality' in rules
    # V3.19.2: levels 5-6 keep the lingerie completely hidden in public scenes.
    assert 'completely hidden underneath' in rules
    # Level-1 realism is preserved, now with the explicit layering guard.
    assert 'only her natural feminine silhouette reads through the fitted fabric' in rules
    assert 'never on top of or outside the outfit' in rules
    assert 'lace edge' in rules


def test_hairstyle_pool_has_at_least_20_styles():
    pool = PHOTO[PHOTO.index('HAIRSTYLE_POOL = ['):PHOTO.index(']\n\nMAKEUP_POOL')]
    assert pool.count("'") // 2 >= 20


def test_gemini_video_auto_enabled_with_key():
    assert '_GEMINI_VIDEO_FLAG = os.getenv("GEMINI_VIDEO_ENABLED", "auto")' in CONFIG
    assert '_GEMINI_VIDEO_FLAG not in {"0", "false", "no", "off"}' in CONFIG
    # The default HF space is an image-to-video space now.
    assert 'HF_VIDEO_SPACE = os.getenv("HF_VIDEO_SPACE", "Wan-AI/Wan2.2-I2V-A14B")' in CONFIG
    assert 'multiverseai/mochi' not in CONFIG


def test_admin_gets_video_failure_diagnostics():
    job = MAIN[MAIN.index('async def _run_video_background('):]
    job = job.split('\n\n\n@dp.', 1)[0]
    assert 'if telegram_id in ADMIN_TELEGRAM_IDS:' in job
    assert '🔧 диагностика видео' in job


def test_photo_variety_accessories_and_time_of_day():
    assert 'ACCESSORY_POOL = [' in PHOTO
    accessories = PHOTO[PHOTO.index('ACCESSORY_POOL = ['):PHOTO.index(']', PHOTO.index('ACCESSORY_POOL = ['))]
    assert accessories.count("'") // 2 >= 8
    assert 'DAYLIGHT_POOL = [' in PHOTO
    daylight = PHOTO[PHOTO.index('DAYLIGHT_POOL = ['):PHOTO.index(']', PHOTO.index('DAYLIGHT_POOL = ['))]
    assert daylight.count("'") // 2 >= 5
    # Requests carry both fields and the prompt injects them.
    assert 'accessory: str' in PHOTO
    assert 'time_of_day: str' in PHOTO
    assert 'random.choice(ACCESSORY_POOL)' in PHOTO
    assert 'random.choice(DAYLIGHT_POOL)' in PHOTO
    build = PHOTO[PHOTO.index('def _build_prompt('):]
    build = build.split('\ndef _extract_openai_many', 1)[0]
    assert 'STYLING DETAILS: {request.accessory}' in build
    assert 'TIME OF DAY: {request.time_of_day}' in build
