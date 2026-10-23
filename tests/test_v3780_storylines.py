"""V3.78.0: «🎬 Сюжеты» — seven Premium storylines for every girl of the
«Персиковый сад» roster; she opens the scene and keeps the role a day."""
import os
import re
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")

import pytest  # noqa: E402

from services import storylines as st  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
CARDS = (ROOT / 'services' / 'character_card_service.py').read_text(encoding='utf-8')


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(st, '_state', {})


def _official_girls():
    block = CARDS.split('DEFAULT_CARDS = {', 1)[1].split('\n}', 1)[0]
    out = []
    for cid, body in re.findall(r'"(\w+_01)": \{(.*?)\n    \}', block, re.S):
        if '"gender": "female"' in body and '"status": "active"' in body:
            out.append(cid)
    return out


def test_every_girl_has_seven_storylines():
    girls = _official_girls()
    assert len(girls) >= 28
    for cid in girls:
        plots = st.for_character(cid)
        assert len(plots) == 7, cid
        assert len({p.key for p in plots}) == 7, cid


def test_storylines_are_adult_only_and_fit_the_ui():
    for cid in _official_girls():
        for p in st.for_character(cid):
            blob = ' '.join([p.title, p.teaser, p.her_role, p.his_role, p.place, p.opening]).lower()
            for bad in ('школ', 'школьн', 'студентк', 'student', 'school', 'teen', 'подрост', 'урок',
                        'сестрён', 'мачех', 'отчим', 'несовершеннолет'):
                assert bad not in blob, (cid, p.key, bad)
            assert len(p.title) <= 28 and len(p.teaser) <= 90, (cid, p.key)
            assert 20 <= len(p.opening) <= 400, (cid, p.key)
            assert re.fullmatch(r'[a-z_]+', p.key), (cid, p.key)


def test_start_keeps_her_in_the_plot_for_a_day(monkeypatch):
    p = st.get('nika_01', 'cut')
    st.start(1, p)
    assert st.active(1, 'nika_01').key == 'cut'
    line = st.direction_for(1, 'nika_01', 'Ника')
    assert 'СЮЖЕТ «Порез»' in line and 'взрослые' in line
    assert st.direction_for(1, 'anna_01') == ''
    later = st._now() + timedelta(hours=st.ACTIVE_HOURS + 1)
    monkeypatch.setattr(st, '_now', lambda: later)
    assert st.active(1, 'nika_01') is None


def test_public_list_hides_the_script():
    item = st.public_list('anna_01')[0]
    assert set(item) == {'key', 'emoji', 'title', 'teaser'}


def test_wiring_premium_only():
    assert "'/webapp/api/storylines'" in MAIN and "'/webapp/api/storyline/start'" in MAIN
    start = MAIN.split('async def _webapp_api_storyline_start', 1)[1].split('\nasync def ', 1)[0]
    assert "not is_premium(telegram_id)" in start and "'premium_required'" in start
    assert 'is_adult_confirmed(telegram_id)' in start
    assert 'plot_direction_for(user_id, character_id' in CHAT
    assert 'id="charPlots"' in INDEX and 'id="featPlots"' in INDEX and 'async function startPlot' in INDEX
