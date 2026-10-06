"""V3.55.0 — «Мои видео» + motion presets + gallery-set badges.

The studio 🎬 mode gains the bot's own motion presets: the client sends only a
KEY of cloud_video_service.VIDEO_PRESETS and the server substitutes the fixed
engine prompt, so free user text never forms the motion when a preset is
chosen (and the scene-gated sensual preset stays unreachable in this route —
pinned by the V3.54.0 suite). Below the generator a «Мои видео» gallery lists
the user's app-rendered clips from the UserGeneration audit rows; the bytes
live in Postgres ChatMedia and /webapp/media re-materializes them on disk, so
the gallery survives Railway redeploys with no new schema.

The V3.53.0 backlog closes too: completing a 50-photo gallery set unlocks two
cosmetic achievements (no peaches, no Stars — the standing owner decision),
hooked into the single detection point note_gallery_set().

Static pins only (no imports -> the suite runs without a DB or an LLM key)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
COLL = (ROOT / 'services' / 'collection_service.py').read_text(encoding='utf-8')
GAM = (ROOT / 'services' / 'gamification_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')

_VID_START = MAIN.index('async def _webapp_api_studio_video(')
VIDEO_FN = MAIN[_VID_START:MAIN.index('async def _webapp_pipeline_photo(', _VID_START)]
_VLIST_START = MAIN.index('async def _webapp_api_videos(')
VIDLIST_FN = MAIN[_VLIST_START:MAIN.index('async def _webapp_api_picture_generate(', _VLIST_START)]


def test_video_list_reads_the_audit_table_newest_first():
    assert 'def api_video_list(' in WEBAPP_SVC
    assert "UserGeneration.kind == 'video'" in WEBAPP_SVC
    assert 'UserGeneration.filename.is_not(None)' in WEBAPP_SVC
    assert 'UserGeneration.created_at.desc()' in WEBAPP_SVC
    # served through the owner-scoped, Postgres-backed media route
    assert "'/webapp/media/{row.filename}'" in WEBAPP_SVC or 'f"/webapp/media/{row.filename}"' in WEBAPP_SVC


def test_videos_route_registered_and_authed():
    assert 'async def _webapp_api_videos(' in MAIN
    assert "app.router.add_get('/webapp/api/videos', _webapp_api_videos)" in MAIN
    # same owner-scoped auth model as /webapp/api/pictures: bad init_data and
    # a user without an id both answer 401 before anything is listed
    assert VIDLIST_FN.count("'error': 'auth'}, status=401") >= 2
    assert 'validate_init_data' in VIDLIST_FN
    assert 'webapp_service.api_video_list(telegram_id)' in VIDLIST_FN


def test_studio_video_preset_key_only_motion():
    # the client sends a key; the server picks the fixed engine prompt
    assert "preset = str(body.get('preset', '')).strip()" in VIDEO_FN
    assert 'motion = VIDEO_PRESETS[preset][1] if preset in VIDEO_PRESETS else (prompt or None)' in VIDEO_FN
    # unknown keys fall through to the old neutral behavior; the preset is
    # audited in the analytics event
    assert "'preset': preset" in VIDEO_FN
    # VIDEO_PRESETS is imported at module top, so no inline sensual prompt and
    # no free client text can reach the motion when a preset was picked
    assert 'from services.cloud_video_service import' in MAIN


def test_gallery_set_badges_are_cosmetic_and_hooked_once():
    assert "'gallery_set_first': ('Первый сет'" in GAM
    assert "'gallery_set_five': ('Марафонец галерей'" in GAM
    # cosmetic-only rewards (the standing owner decision: no peaches, no Stars)
    assert "'gallery_set_first': ('Первый сет', 'Собрал(а) галерею персонажа — 50 фото', [])" in GAM
    assert "'gallery_set_five': ('Марафонец галерей', 'Собрано пять сетов', [])" in GAM
    # both sit on the unified board/missions roadmap
    assert "'gallery_set_first': 'romance'" in GAM
    # the unlock rides the single detection point, fail-silent
    assert "unlock_achievement(tg, 'gallery_set_first')" in COLL
    assert "unlock_achievement(tg, 'gallery_set_five')" in COLL
    assert 'sum(int(v or 0) for v in current.values()) >= 5' in COLL


def test_spa_preset_chips_and_video_gallery():
    assert "let PIC_PRESET = '';" in SPA
    assert 'id="vidPresetRow"' in SPA
    assert 'function studioPresetChips()' in SPA
    # only the key travels; re-tap clears back to auto
    assert '...(PIC_PRESET ? { preset: PIC_PRESET } : {})' in SPA
    assert 'async function loadStudioVideos()' in SPA
    assert "'/webapp/api/videos?init_data=' + encodeURIComponent" in SPA
    assert 'id="vidGallery"' in SPA
    assert '<div class="vgal">' in SPA
    # populated on mode switch and on the first visit of the pics tab
    assert "if (PIC_MODE === 'video') loadStudioVideos();" in SPA
    assert "if(PIC_MODE==='video')loadStudioVideos();" in SPA
    # the gallery renders real players, owner-scoped like every media tile
    assert SPA.count('<video controls playsinline') >= 2


def test_spa_has_all_seven_locale_strings():
    for key in ('videos_title:', 'videos_empty:', 'preset_auto:', 'preset_kiss:',
                'preset_wink:', 'preset_turn:', 'preset_whisper:',
                'preset_touch:', 'preset_caress:'):
        assert SPA.count(key) >= 7, key
