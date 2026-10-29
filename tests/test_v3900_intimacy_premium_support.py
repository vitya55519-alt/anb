"""V3.90.0: owner — «весь интим только с премиумом, и проработай бот
поддержки»."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_explicit_sexting_needs_premium():
    from services.chat_service import EXPLICIT_CHAT_RULE, explicit_chat_line
    assert explicit_chat_line('committed', adult_confirmed=True) == ''
    assert explicit_chat_line('committed', adult_confirmed=True, premium=True) == EXPLICIT_CHAT_RULE
    assert explicit_chat_line('close', adult_confirmed=True, card_girl=True) == ''
    assert explicit_chat_line('close', adult_confirmed=True, card_girl=True, premium=True) == EXPLICIT_CHAT_RULE
    assert explicit_chat_line(None, adult_confirmed=True, wild=True, premium=False) == ''


def test_chat_prompt_wiring():
    assert 'wild=plot_heat == \'wild\', premium=intim_ok)' in CHAT
    assert 'if card_girl and not spicy_line and intim_ok and _adult_ok(user_id):' in CHAT
    assert 'NON_PREMIUM_LINE' in CHAT


def test_sext_offer_detection():
    from services.intimacy_gate import wants_sext
    assert wants_sext('давай займёмся сексом')
    assert wants_sext('хочу тебя прямо сейчас')
    assert wants_sext('разденься для меня')
    assert not wants_sext('как прошёл твой день?')
    assert not wants_sext('пришли селфи')


def test_sext_offer_wired_in_app_and_bot():
    assert "payload['sext_offer'] = True" in MAIN
    assert 'intimacy_gate.OFFER_TEXT_RU' in MAIN
    assert 'if (j.sext_offer)' in HTML
    assert HTML.count('sext_btn:') >= 2


def test_support_desk_helpers():
    from services import support_desk as desk
    assert desk.user_id_from_card('🆘 Обращение от Миша\nid: 1234567\n...') == 1234567
    assert desk.user_id_from_card('привет') is None
    assert desk.parse_reply_command('/reply 1234567 Начислили, проверь') == (1234567, 'Начислили, проверь')
    assert desk.parse_reply_command('/reply abc') is None
    assert 'pay' in desk.FAQ and 'premium' in desk.FAQ
    assert desk.tickets_text([]) == 'Открытых обращений нет ✅'


def test_support_bot_admin_flow():
    assert "if uid in ADMIN_TELEGRAM_IDS:" in MAIN
    assert "desk.user_id_from_card(reply.text or reply.caption)" in MAIN
    assert "@support_dp.message(Command('tickets'))" in MAIN
    assert "desk.ACK_EVERY.total_seconds()" in MAIN
