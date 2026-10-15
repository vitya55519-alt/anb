"""V3.62.0: ten levels, two paths (romance / passion) chosen at level 3."""
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _row(stage, branch=None, **kw):
    base = dict(stage=stage, relationship_score=91, trust_score=86, intimacy_score=81,
                familiarity_score=66, continuity_score=36, connection_score=36,
                total_messages=500, id=None, path_axis=0.0, branch=branch,
                first_interaction_at=datetime.utcnow() - timedelta(days=9))
    base.update(kw)
    return SimpleNamespace(**base)


def test_ten_levels_and_names_per_path():
    from services.relationship_engine import STAGE_ORDER, level_title, PREMIUM_STAGES
    from services.photo_service import STAGE_INDEX
    from services.test_mode import STAGES
    assert len(STAGE_ORDER) == 10 and len(STAGES) == 10
    assert STAGE_INDEX['eternal'] == 9 and 'voyage' in PREMIUM_STAGES
    assert level_title(3) == 'Искра'
    assert level_title(5, 'romance') == 'Первое свидание' and level_title(5, 'passion') == 'Игра'
    assert level_title(8, 'romance', taken=True) == 'Наше тайное место'
    assert level_title(10, 'passion') == 'Без правил'
    assert len({level_title(n, b) for b in ('romance', 'passion') for n in range(4, 11)}) == 14


def test_levels_9_10_need_more_time_together():
    from services.relationship_engine import _dimension_stage
    full = dict(relationship_score=100, trust_score=100, intimacy_score=100, familiarity_score=100)
    assert _dimension_stage(_row('stranger', **full, continuity_score=56, connection_score=56)) == 'soulmate'
    assert _dimension_stage(_row('stranger', **full, continuity_score=66, connection_score=66)) == 'voyage'
    assert _dimension_stage(_row('stranger', **full, continuity_score=80, connection_score=80)) == 'eternal'


def test_snapshot_has_fork_branch_and_map():
    from services.relationship_engine import level_snapshot
    snap = level_snapshot(None, _row('close'), premium=True)
    assert snap['fork'] is True and snap['branch'] is None
    assert snap['map']['romance'][0]['state'] == 'choose'
    snap = level_snapshot(None, _row('deeply_connected', branch='passion'), premium=True)
    assert snap['title'] == 'Игра' and snap['fork'] is False and snap['branch_label'] == '🔥 Путь страсти'
    assert snap['map']['romance'][0]['state'] == 'other'
    assert [x['state'] for x in snap['map']['passion'][:3]] == ['done', 'current', 'locked']
    assert snap['next_title'] == 'Без тормозов'
    assert level_snapshot(None, _row('stranger'), premium=True)['fork'] is False


def test_tone_follows_the_path():
    from services.relationship_engine import build_relationship_context
    passion = build_relationship_context(_row('intimate', branch='passion'), character_id='anna_01')
    romance = build_relationship_context(_row('intimate', branch='romance'), character_id='anna_01')
    assert 'Искушение' in passion and 'Влюблённость' in romance
    secret = build_relationship_context(_row('soulmate', branch='passion'), character_id='anna_01', marital='mar_married')
    assert 'тайные любовники' in secret and 'живёте вместе' not in secret


def test_ceremony_scenes_and_fork_flow():
    assert 'LEVEL_UP_SCENES_PASSION = {' in MAIN and 'def _level_up_scene(' in MAIN
    assert "'eternal': (" in MAIN and 'engagement ring' in MAIN
    assert 'branch_service.maybe_offer_fork' in MAIN and 'branch_service.mark_left_him' in MAIN
    assert "app.router.add_post('/webapp/api/chat/branch', _webapp_api_chat_branch)" in MAIN
    assert "m.media_kind === 'fork'" in SPA and 'function pathMapHtml(j)' in SPA
    assert "'/webapp/api/chat/branch?init_data='" in SPA


def test_branch_choice_round_trip(monkeypatch):
    from services.db import SessionLocal, init_db
    init_db()
    from services import branch_service
    from services.relationship_engine import get_state, set_branch, apply_delta, RelationshipDelta
    from services.user_service import ensure_user
    uid = ensure_user(990011)
    with SessionLocal() as s:
        row = apply_delta(s, uid, 'anna_01', RelationshipDelta())
        row.stage = 'close'
        s.commit()
    assert branch_service.maybe_offer_fork(uid, 'anna_01') is True
    assert branch_service.maybe_offer_fork(uid, 'anna_01') is True  # offered once
    assert branch_service.choose(uid, 'anna_01', 'passion')
    assert branch_service.choose(uid, 'anna_01', 'romance') is None
    assert set_branch(uid, 'anna_01', 'romance') is False
    with SessionLocal() as s:
        row = get_state(s, uid, 'anna_01')
        assert row.branch == 'passion' and row.path_axis >= 50 and row.persona_style == 'passionate'
    assert branch_service.maybe_offer_fork(uid, 'anna_01') is False
