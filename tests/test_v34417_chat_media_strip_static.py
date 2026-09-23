"""V3.44.17 static checks: the chat media strip loses the video/circle pills.

Owner request: «скрой из чата кнопки видео и кружок» — the Mini App chat input
row showed «Видео» (direct AI clip) and «Кружок» (video note) pills next to
«Фото». Both are hidden: the two buttons, their click listeners and their
label assignments are removed from webapp/index.html. Everything behind them
stays — the /webapp/api/media endpoints, the engine chains, the history
renderers (old video/circle bubbles still display) and the i18n keys — so
restoring the buttons later is a plain revert of this change.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_video_and_circle_buttons_removed_from_the_strip():
    assert 'id="mediaVideo"' not in INDEX
    assert 'id="mediaCircle"' not in INDEX
    assert 'id="lbMediaVideo"' not in INDEX
    assert 'id="lbMediaCircle"' not in INDEX


def test_click_listeners_removed():
    assert "getElementById('mediaVideo')" not in INDEX
    assert "getElementById('mediaCircle')" not in INDEX
    assert "requestMedia('video')" not in INDEX
    assert "requestMedia('circle')" not in INDEX


def test_label_assignments_removed():
    assert "document.getElementById('lbMediaVideo').textContent" not in INDEX
    assert "document.getElementById('lbMediaCircle').textContent" not in INDEX


def test_remaining_pills_stay_wired():
    # photo opens the scene picker (V3.43.7), the three feature pills open the
    # feature sheet — nothing else in the strip regressed
    assert 'id="mediaPhoto"' in INDEX
    assert "getElementById('mediaPhoto').addEventListener('click', () => openFeature('photo'))" in INDEX
    for feat in ('featQuest', 'featDate', 'featApt'):
        assert f'id="{feat}"' in INDEX
    assert "getElementById('featQuest').addEventListener('click', () => openFeature('quest'))" in INDEX
    assert "getElementById('featDate').addEventListener('click', () => openFeature('date'))" in INDEX
    assert "getElementById('featApt').addEventListener('click', () => openFeature('apartment'))" in INDEX
    # the strip styling itself stays
    assert '.chat-media button .ic {' in INDEX
    assert '.chat-media button .lb {' in INDEX


def test_photo_media_pipeline_untouched():
    # requestMedia keeps its signature; the only live caller is the photo
    # scene picker, the chosen scene rides the media request (V3.43.7)
    assert 'async function requestMedia(kind, scene)' in INDEX
    assert "requestMedia('photo', el.dataset.scene)" in INDEX


def test_backend_media_endpoints_stay_for_a_plain_revert():
    # the app video/circle pipelines remain registered in main.py — the
    # buttons are hidden, the feature is not torn out
    assert 'async def _webapp_media_video(telegram_id: int, character_id: str):' in MAIN
    assert 'async def _webapp_media_circle(' in MAIN
    assert 'async def _webapp_media_scene(telegram_id: int, character_id: str, scene: str):' in MAIN


def test_history_renderers_stay():
    # already-delivered video/circle messages must keep rendering in the
    # dialog history even though the buttons are gone
    assert "m.media_kind === 'video'" in INDEX
    assert 'video class="circle"' in INDEX
    assert '<audio controls src=' in INDEX


def test_i18n_keys_kept_for_the_revert():
    # the localized labels/wait strings stay in the L dicts (unused but
    # harmless) so bringing the pills back needs no translation work
    assert "media_wait_video: 'Рисую видео — 1–3 минуты…'" in INDEX
    assert "media_wait_video: 'Rendering a video — 1–3 min…'" in INDEX
    assert "media_wait_circle: 'Записываю кружочек — 1–3 минуты…'" in INDEX
    assert "media_wait_circle: 'Recording a circle — 1–3 min…'" in INDEX
