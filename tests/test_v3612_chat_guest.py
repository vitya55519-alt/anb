"""V3.61.2: «позвать в чат» — a second girl invited into one girl's chat."""
from pathlib import Path

from services.db import init_db
from services.character_card_service import ensure_default_cards
from services import chat_guest_service as cgs

ROOT = Path(__file__).resolve().parents[1]


def setup_module(_):
    init_db()
    ensure_default_cards()


def test_guest_is_stored_and_cleared():
    cgs.set_guest(777001, 'anna_01', 'vika_01')
    assert cgs.get_guest(777001, 'anna_01') == 'vika_01'
    assert cgs.get_guest(777001, 'vika_01') is None
    cgs.set_guest(777001, 'anna_01', 'mila_01')
    assert cgs.get_guest(777001, 'anna_01') == 'mila_01'
    cgs.set_guest(777001, 'anna_01', None)
    assert cgs.get_guest(777001, 'anna_01') is None


def test_cannot_invite_herself_or_unknown():
    assert not cgs.can_invite(777001, 'anna_01', 'anna_01')
    assert not cgs.can_invite(777001, 'anna_01', 'nobody_99')
    assert cgs.can_invite(777001, 'anna_01', 'vika_01')


def test_guest_prompt_names_both_speakers():
    line = cgs.guest_prompt('Анна', 'vika_01')
    assert 'Вика' in line and '«Анна: …»' in line and '«Вика: …»' in line
    assert 'взрослые' in line


def test_chat_pipeline_and_spa_wiring():
    chat = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
    assert 'guest_prompt(' in chat and 'guest_reminder' in chat
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "'/webapp/api/chat/guest'" in main and "'can_invite'" in main
    html = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    for marker in ('id="chatInvite"', 'id="guestBar"', 'openGuestPicker', 'setGuest('):
        assert marker in html
