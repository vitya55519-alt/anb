"""V3.61.6: clear photo-scene names, one-line hints, instant menu, concrete scenes."""
from pathlib import Path

from services import photo_service as ps

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')

PUBLIC = ['home', 'park', 'cafe', 'street', 'shop', 'car', 'gym', 'mirror', 'outfit', 'restaurant',
          'cinema', 'embankment', 'evening', 'fashion', 'bar', 'karaoke', 'rooftop', 'club']


def test_confusing_names_are_gone():
    for old in ("sc_outfit: '👗 Образ'", "sc_fashion: '💎 Fashion', sc_evening: '✨ Вечер'",
                "sc_private_fashion: '🔐 Premium private'", "'🖤 Приватный fashion'"):
        assert old not in INDEX
    for new in ('👗 Мой наряд сегодня', '💎 Фотосессия', '🔐 Будуар', '🖤 В кружевном белье'):
        assert new in INDEX


def test_every_menu_scene_has_a_hint():
    for scene in PUBLIC + ['selfie', 'personal', 'lingerie', 'private_fashion']:
        assert f'sch_{scene}:' in INDEX, scene


def test_photo_menu_opens_from_cache():
    assert 'function prefetchPhotoMenu(characterId)' in INDEX
    assert 'prefetchPhotoMenu(characterId);' in INDEX
    assert "PHOTO_MENU_CACHE[CHAT.id] = j" in INDEX


def test_public_scenes_are_concrete_and_have_three_shots():
    for scene in PUBLIC:
        assert len(ps.SCENES[scene]) > 90, scene
        assert len(ps.SHOT_VARIANTS[scene]) == 3, scene
        assert '«' not in ps.SCENES[scene]
