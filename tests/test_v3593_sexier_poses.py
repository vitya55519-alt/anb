"""V3.59.3: hotter poses and faces in the intimate scenes only."""
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-for-static-tests-only")

ROOT = Path(__file__).resolve().parents[1]
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def test_private_rotation_has_arousal_faces_public_does_not():
    from services import photo_expression_service as e
    priv = e.shuffled_private_sensual_keys()
    assert {'pleasure', 'breathless'} <= set(priv) and len(priv) == len(set(priv))
    assert 'pleasure' not in e.SENSUAL_KEYS and 'pleasure' not in e.VARIETY_KEYS
    assert e.expression_description('pleasure', 'Anna').startswith('EXPRESSION: Anna has an aroused')


def test_self_touch_poses_in_both_private_pools():
    from services import photo_service, private_photo_service
    for pool in (photo_service.PRIVATE_POSE_POOL, private_photo_service.PRIVATE_POSE_POOL):
        touch = [p for p in pool if 'five correct fingers' in p]
        assert len(touch) >= 5
    assert "else shuffled_private_sensual_keys() if (request.scene in {'personal', 'lingerie', 'private_fashion', 'tease'} or passion)" in PHOTO


def test_passion_path_heats_every_scene():
    assert "passion = _path_is_passion(telegram_id, character_id)" in PHOTO
    assert "or passion)" in PHOTO
    assert "if passion and request.scene not in {'personal', 'lingerie', 'private_fashion', 'tease'}:" in PHOTO
    from services import photo_service
    assert len(photo_service.PASSION_PUBLIC_POSE_POOL) >= 5
    assert photo_service.PASSION_PATH_THRESHOLD == 20.0


MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_choice_points_match_the_axis_step():
    from services import quest_service as q
    assert q.path_points('bold') == 8 and q.path_points('romance') == -8 and q.path_points(None) == 0
    assert q.route_points('photo_hint', 'confident') == 8
    assert q.route_points('photo_hint', 'dreamy') == -8
    key = next(iter(q.QUEST_BRANCHES))
    opts = q._beat_options(*key)['options']
    for ok, ov in q.QUEST_BRANCHES[key]['options'].items():
        assert opts[ok]['points'] == q.path_points(ov.get('inclination'))


def test_story_buttons_show_points():
    assert "'points': route_points(st['key'], rk) if not st['canonical'] else 0}" in MAIN
    assert 'function storyPtsTag(points)' in SPA
    assert "storyPtsTag(rt.points)" in SPA and "storyPtsTag(bo.options[ok].points)" in SPA
    assert "story_pts_passion: 'к страсти', story_pts_tender: 'к нежности'" in SPA


def test_admin_can_set_own_path():
    assert "callback_data='admin:path'" in MAIN
    assert "@dp.callback_query(F.data.startswith('admin:pathset:'))" in MAIN
    assert MAIN.count('if cq.from_user.id not in ADMIN_TELEGRAM_IDS:') >= 2
    from services.db import init_db
    init_db()
    from services.user_service import ensure_user
    from services.relationship_engine import set_path_axis, get_path_axis
    uid = ensure_user(990011)
    assert set_path_axis(uid, 'anna_01', 250) == 100.0
    assert get_path_axis(uid, 'anna_01') == 100.0
    set_path_axis(uid, 'anna_01', -25)
    assert get_path_axis(uid, 'anna_01') == -25.0
