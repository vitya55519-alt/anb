"""V3.102.0 — «🎭 Фетиши»: a Premium theme mode she leads at any level, with fixed limits."""
from pathlib import Path

from services import fetish_mode as fm

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_theme_list_is_adult_and_complete():
    keys = [f[0] for f in fm.FETISHES]
    assert len(keys) == len(set(keys)) >= 12
    for _k, _e, ru, en, desc, opening in fm.FETISHES:
        assert ru and en and desc and opening
    low = ' '.join(f[4].lower() + ' ' + f[5].lower() for f in fm.FETISHES)
    for bad in ('школьн', 'ребён', 'малолет', 'насил', 'животн'):
        assert bad not in low


def test_custom_text_limits():
    assert fm.clean_custom('щекотка перьями') == 'щекотка перьями'
    assert fm.clean_custom('секс на кровати') == 'секс на кровати'
    assert fm.clean_custom('детали игры') == 'детали игры'
    for bad in ('школьница', 'детская форма', 'изнасилование', 'собаки', 'hot teen', 'инцест', 'кровь', 'ab', ''):
        assert fm.clean_custom(bad) is None, bad
    assert len(fm.clean_custom('а' * 200)) <= fm.CUSTOM_MAX


def test_start_stop_and_direction(monkeypatch):
    store = {}
    monkeypatch.setattr(fm, '_state', store)
    assert fm.direction_for(1, 'anna_01') == ''
    out = fm.start(1, 'anna_01', key='feet')
    assert out and out['key'] == 'feet' and out['opening']
    line = fm.direction_for(1, 'anna_01', 'Анна')
    assert 'РЕЖИМ ФЕТИШЕЙ' in line and 'Ножки' in line and 'без несовершеннолетних' in line
    assert fm.status(1, 'anna_01')['key'] == 'feet'
    assert fm.direction_for(1, 'other_01') == ''  # per girl
    assert fm.start(1, 'anna_01', key='nope') is None
    assert fm.start(1, 'anna_01', key='', custom='школьница') is None
    custom = fm.start(2, 'anna_01', key='', custom='массаж ног')
    assert custom['key'] == 'custom' and 'массаж ног' in fm.direction_for(2, 'anna_01')
    assert fm.stop(1, 'anna_01') and fm.direction_for(1, 'anna_01') == ''
    assert not fm.stop(1, 'anna_01')


def test_expired_theme_is_off(monkeypatch):
    store = {1: {'anna_01': {'key': 'feet', 'custom': '', 'until': '2000-01-01T00:00:00'}}}
    monkeypatch.setattr(fm, '_state', store)
    assert fm.direction_for(1, 'anna_01') == '' and fm.status(1, 'anna_01') is None


def test_chat_uses_theme_only_for_premium_adults():
    assert 'fetish_mode.direction_for(' in CHAT
    assert 'if premium or _is_admin(user_id):' in CHAT
    assert CHAT.index('if premium or _is_admin(user_id):') < CHAT.index('fetish_mode.direction_for(')
    assert "wild=plot_heat == 'wild' or bool(fetish_line)" in CHAT


def test_api_and_app_wiring():
    for route in ("'/webapp/api/fetishes'", "'/webapp/api/fetish/set'", "'/webapp/api/fetish/stop'"):
        assert route in MAIN
    api = MAIN[MAIN.index('async def _webapp_api_fetish_set'):MAIN.index('async def _webapp_api_fetish_stop')]
    assert "'premium_required'" in api and "'adult'" in api and "'refused'" in api
    assert 'id="featFetish"' in SPA and 'id="fetishSheet"' in SPA and 'openFetishSheet' in SPA
    assert 'fet_cap:' in SPA and SPA.count('fet_locked:') == 2
