"""V3.54.0 — «Своё фото → картинка / видео» (studio upload media).

The «Картинки» studio gains a 🖼/🎬 mode switch and an own-photo upload:
* picture mode can run image-to-image over the uploaded photo — always on the
  CENSORED engines (generate_custom_avatar), so a real uploaded face never
  reaches the uncensored nude route, whatever the user's 18+ flag says;
* video mode animates the uploaded photo (or a prompt-rendered frame when no
  photo is given) through the shared engine chain Gemini/Veo → Replicate → fal
  → HF, with a NEUTRAL motion prompt only.

The upload itself is never persisted (temp file unlinked after the render);
a video costs WEBAPP_VIDEO_COST_CREDITS 🍑, charged only after success, and is
saved through save_chat_media (Postgres-backed, survives redeploys).

Static pins only (no imports -> the suite runs without a DB or an LLM key)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')

# the full body of the new route, for order/negation pins
_VID_START = MAIN.index('async def _webapp_api_studio_video(')
VIDEO_FN = MAIN[_VID_START:MAIN.index('async def _webapp_pipeline_photo(', _VID_START)]


def test_service_video_price_and_upload_guardrails():
    # V3.55.5: the video price is the single unified peach-rail knob from
    # config (VIDEO_PEACH_COST, default 20 🍑), charged only on success
    assert 'WEBAPP_VIDEO_COST_CREDITS = VIDEO_PEACH_COST' in WEBAPP_SVC
    assert 'VIDEO_PEACH_COST = max(1, int(os.getenv("VIDEO_PEACH_COST", "20")))' in CONFIG
    # the decoder is fail-safe and bounded: 8 MB cap + mime allowlist
    assert 'def decode_data_image(' in WEBAPP_SVC
    assert 'STUDIO_UPLOAD_MAX_BYTES = 8 * 1024 * 1024' in WEBAPP_SVC
    assert "'image/jpeg': 'jpg'" in WEBAPP_SVC
    assert "'image/png': 'png'" in WEBAPP_SVC
    assert "'image/webp': 'webp'" in WEBAPP_SVC
    # the ``data:`` scheme must be stripped before the mime allowlist lookup
    # (a local smoke run caught it: without this the decoder rejects everything)
    assert "mime.startswith('data:')" in WEBAPP_SVC


def test_picture_route_img2img_is_censored_only():
    # an uploaded data URL becomes a temp file threaded as reference_path
    assert "webapp_service.decode_data_image(str(body.get('image')))" in MAIN
    assert 'generate_custom_avatar(final_prompt, ref_path)' in MAIN
    # the adult uncensored leg is gated OFF whenever a photo was uploaded
    assert 'adult_ok = is_adult_confirmed(telegram_id) and ref_path is None' in MAIN
    # the upload never lingers, whatever the render outcome
    assert 'ref_path.unlink(missing_ok=True)' in MAIN


def test_studio_video_route_exists_and_wired():
    assert 'async def _webapp_api_studio_video(' in MAIN
    assert "app.router.add_post('/webapp/api/studio/video', _webapp_api_studio_video)" in MAIN
    # consent + price gates mirror the picture studio
    assert 'if not has_accepted(telegram_id):' in VIDEO_FN
    assert 'get_photo_credits(telegram_id) < webapp_service.WEBAPP_VIDEO_COST_CREDITS' in VIDEO_FN


def test_studio_video_uses_shared_engine_chain_and_neutral_motion():
    # the same availability order as the bot's video flow
    for pin in (
        "('gemini', animate_image)",
        "('replicate', animate_image_replicate)",
        "('fal', animate_image_fal)",
        "('hf', animate_image_hf)",
    ):
        assert pin in VIDEO_FN
    # an uploaded photo is animated with a neutral hint — never the bot's
    # sensual preset, whatever the prompt says (V3.55.0: the free-text branch
    # survives as the fallback behind a chosen motion preset)
    assert 'else (prompt or None)' in VIDEO_FN
    assert 'SENSUAL' not in VIDEO_FN


def test_studio_video_saves_then_charges_only_on_success():
    # no frame + no photo -> 400 before any engine is touched
    assert "generate_custom_avatar(final_prompt, None)" in VIDEO_FN
    # persistence rides save_chat_media (Postgres), then the audit row,
    # and the charge happens strictly after both
    assert "save_chat_media(telegram_id, video_bytes, 'mp4', 'video/mp4')" in VIDEO_FN
    save_i = VIDEO_FN.index("save_chat_media(telegram_id, video_bytes, 'mp4'")
    spend_i = VIDEO_FN.index('spend_peaches(telegram_id, webapp_service.WEBAPP_VIDEO_COST_CREDITS)')
    assert save_i < spend_i
    assert "record_generation(telegram_id, 'video', None, prompt, filename)" in VIDEO_FN
    # a failed render must return BEFORE any spend line exists in the flow
    fail_i = VIDEO_FN.index("if not video_bytes:")
    assert fail_i < spend_i


def test_spa_mode_switch_upload_and_video_render():
    assert "let PIC_MODE = 'pic';" in SPA
    assert 'let PIC_UPLOAD = null;' in SPA
    assert 'function switchStudioMode(' in SPA
    # a plain file picker is what the Mini App WebView allows
    assert 'accept="image/*"' in SPA
    assert 'readAsDataURL' in SPA
    # the data URL rides the one request in both modes
    assert SPA.count('...(PIC_UPLOAD ? { image: PIC_UPLOAD } : {})') >= 2
    assert 'async function generateStudioVideo()' in SPA
    assert "'/webapp/api/studio/video?init_data=' + encodeURIComponent" in SPA
    assert '<video controls playsinline' in SPA


def test_spa_has_all_seven_locale_strings():
    for key in ('mode_pic:', 'mode_video:', 'upload_photo:', 'upload_remove:',
                'video_prompt_ph:', 'video_generate:', 'video_wait:',
                'video_fail:', 'need_prompt_or_photo:'):
        assert SPA.count(key) >= 7, key
