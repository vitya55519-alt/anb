"""V3.134.0 — истории семейного положения (все 6 пунктов)."""
from pathlib import Path

from models.app_models import Base
from services import marital_arcs as ma
from services.custom_character_service import RELATIONSHIP_STORY
from services.db import engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_each_status_has_its_story():
    assert ma.arc_for('mar_married').key == 'steal' and ma.arc_for('mar_boyfriend').key == 'steal'
    assert ma.arc_for('mar_single').key == 'wedding' and ma.arc_for('mar_with_you').key == 'wedding'
    assert ma.arc_for('mar_divorced').key == 'divorce'
    assert ma.arc_for('mar_open').key == 'third'
    assert ma.arc_for('mar_wife') is None


def test_new_statuses_have_a_voice_and_are_not_for_sale():
    for st in ma.ARC_ONLY_STATUSES:
        assert st in RELATIONSHIP_STORY
    assert 'status in ARC_ONLY_STATUSES' in MAIN
    assert ma.ARCS['steal'].finish_status == 'mar_with_you' and ma.ARCS['wedding'].finish_status == 'mar_wife'


def test_gates_level_premium_adult_and_order():
    steal = ma.ARCS['steal']
    assert ma.check_step(steal, 0, set(), 3, False, True) == ''
    assert ma.check_step(steal, 0, set(), 2, False, True) == 'level'
    assert ma.check_step(steal, 1, set(), 9, True, True) == 'prev'
    assert ma.check_step(steal, 3, {0, 1, 2}, 9, False, True) == 'premium_required'
    third = ma.ARCS['third']
    assert ma.check_step(third, 0, set(), 9, True, False) == 'adult'
    assert ma.ARCS['wedding'].steps[0].ring and ma.ARCS['wedding'].steps[0].level == 8


def test_progress_and_direction_end_after_step_messages():
    Base.metadata.create_all(engine)
    arc = ma.ARCS['divorce']
    ma.start(777001, 'anna_01', arc, 0)
    assert ma.progress(777001, 'anna_01')['arcs']['divorce'] == [0]
    for _ in range(ma.STEP_MESSAGES):
        assert 'После развода' in ma.direction_for(777001, 'anna_01', 'Аня', tick=True)
    assert ma.direction_for(777001, 'anna_01', 'Аня') == ''
    pub = ma.public(777001, 'anna_01', 'mar_divorced', 2, False, True)
    assert [s['state'] for s in pub['arc']['steps']] == ['done', 'next', 'locked']


def test_partner_name_in_her_lines_and_pushes():
    line = ma.opening(ma.ARCS['steal'].steps[2], 'anna_01')
    assert 'Андрей' in line and '{partner}' not in line
    assert 'Андрей' in ma.push_text('mar_married', 'anna_01', rnd=0)
    assert 'бывший' in ma.push_text('mar_single', 'anna_01', rnd=0)
    assert ma.push_text('mar_single', 'anna_01', rnd=0.99) == ''
    assert ma.caught_note('mar_married', 'anna_01', rnd=0) and not ma.caught_note('mar_single', 'anna_01', rnd=0)
    for txt in (t for grp in ma._PUSHES.values() for pair in grp for t in pair):
        for bad in ('обиделась', 'последний шанс', 'если не напишешь'):
            assert bad not in txt


def test_wiring():
    assert "add_get('/webapp/api/marital/arc'" in MAIN and "add_post('/webapp/api/marital/arc/step'" in MAIN
    assert 'spend_peaches(telegram_id, marital_arcs.RING_PEACHES)' in MAIN
    assert 'arc_direction_for(user_id, character_id' in CHAT and 'caught_note(marital_status' in CHAT
    assert 'push_text(guest_marital(telegram_id,char_id),char_id,lang)' in SCHED and '_marital_push(telegram_id,char_id,user_lang)' in SCHED
    assert 'id="charArc"' in HTML and 'function loadMaritalArc(c)' in HTML and '/webapp/api/marital/arc/step' in HTML


def test_next_step_waits_for_a_few_messages():
    arc = ma.ARCS['steal']
    ma.start(777002, 'anna_01', arc, 0)
    item = ma.progress(777002, 'anna_01')
    assert ma.waiting(item, arc)
    assert ma.check_step(arc, 1, {0}, 9, True, True, wait=True) == 'wait'
    for _ in range(ma.WAIT_MESSAGES):
        ma.direction_for(777002, 'anna_01', tick=True)
    assert not ma.waiting(ma.progress(777002, 'anna_01'), arc)
