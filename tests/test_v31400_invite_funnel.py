"""V3.140.0: owner ТЗ (Retention) — три правила удержания.

1. Крючок в конце КАЖДОГО ответа (одиночный и парный чат).
2. В парном чате девушки каждые 3-4 сообщения сначала общаются между собой.
3. В одиночном чате модель сама предлагает позвать подругу; его «давай»
   рождает тег [INVITE_FRIEND] — код вырезает тег, переключает стейт на duo
   и сразу показывает блюр-тизер с кнопкой Premium (пул, без генерации).
"""
from pathlib import Path

from services.db import init_db
from services.character_card_service import ensure_default_cards
from services import invite_funnel as funnel
from services import chat_guest_service as cgs
from services.character_service import build_system_prompt, get_character

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
CUSTOM = (ROOT / 'services' / 'custom_character_service.py').read_text(encoding='utf-8')


def setup_module(_):
    init_db()
    ensure_default_cards()


def _prompt(cid='anna_01'):
    return build_system_prompt(get_character(cid), 'REL', [], character_id=cid)


def test_every_reply_must_end_with_a_hook():
    for cid in ('anna_01', 'alisa_01'):
        t = _prompt(cid)
        assert 'CRITICAL RULE - NEVER STALL THE CHAT' in t
        assert 'MUST end with a direct hook' in t
        assert 'provocative question, a teasing' in t
        # the old «не заканчивай вопросом» rule contradicted the new one
        assert 'НЕ надо каждое сообщение заканчивать вопросом' not in t
        assert 'Каждое сообщение заканчивай крючком' in t


def test_bracket_ban_keeps_the_single_tag_exception():
    t = _prompt()
    assert 'вообще ничего в квадратных скобках' in t
    assert 'Единственное исключение — служебный тег [INVITE_FRIEND]' in t


def test_group_dynamics_live_only_in_duo_prompts():
    assert 'GROUP CHAT DYNAMICS' in cgs.guest_prompt('Анна', 'vika_01')
    assert 'Every 3-4 messages' in cgs.guest_prompt('Анна', 'vika_01')
    assert 'GROUP CHAT DYNAMICS' not in _prompt()
    # the constructor duo gets the same rule right after its two-girl block
    duo = CUSTOM[CUSTOM.index('В ЭТОМ ЧАТЕ ВАС ДВЕ'):]
    assert '+ GROUP_RULE' in duo[:900]


def test_upsell_rule_names_the_friend_and_the_exact_tag():
    r = funnel.upsell_rule('Вика')
    assert 'PROACTIVE UPSELL' in r
    assert 'once every 15-20 messages' in r
    assert 'Вика' in r
    assert '[INVITE_FRIEND]' in r
    assert 'at the very end of your response' in r


def test_strip_tag_cleans_every_occurrence():
    assert funnel.strip_tag('отлично, сейчас напишу ей [INVITE_FRIEND]') == 'отлично, сейчас напишу ей'
    assert funnel.strip_tag('зову [invite_friend]') == 'зову'
    assert funnel.strip_tag('[INVITE_FRIEND] жди [INVITE_FRIEND]') == 'жди'
    assert funnel.strip_tag('без тега') == 'без тега'
    assert funnel.strip_tag('') == ''
    assert funnel.has_tag('да [INVITE_FRIEND]')
    assert not funnel.has_tag('да')


def test_tag_in_solo_chat_switches_state_and_marks_the_teaser():
    tid = 777101
    cgs.set_guest(tid, 'anna_01', None)
    out = funnel.apply('отлично, сейчас напишу ей, жди сюрприз [INVITE_FRIEND]',
                       tid, 'anna_01', duo=False, user_count=10)
    assert out == 'отлично, сейчас напишу ей, жди сюрприз'
    guest = cgs.get_guest(tid, 'anna_01')
    assert guest and guest != 'anna_01'
    # the delivery layer reads the mark exactly once
    assert funnel.take_pending(tid, 'anna_01') == guest
    assert funnel.take_pending(tid, 'anna_01') == ''
    cgs.set_guest(tid, 'anna_01', None)


def test_tag_in_duo_chat_is_only_stripped():
    tid = 777102
    cgs.set_guest(tid, 'anna_01', 'vika_01')
    out = funnel.apply('Анна: зову [INVITE_FRIEND]', tid, 'anna_01', duo=True, user_count=10)
    assert out == 'Анна: зову'
    assert cgs.get_guest(tid, 'anna_01') == 'vika_01'
    assert funnel.take_pending(tid, 'anna_01') == ''
    cgs.set_guest(tid, 'anna_01', None)


def test_plain_answer_never_switches_anything():
    tid = 777103
    cgs.set_guest(tid, 'anna_01', None)
    assert funnel.apply('привет, как ты?', tid, 'anna_01', duo=False, user_count=10) == 'привет, как ты?'
    assert cgs.get_guest(tid, 'anna_01') is None
    assert funnel.take_pending(tid, 'anna_01') == ''


def test_upsell_is_occasional_not_every_message():
    tid = 777104
    assert not funnel.upsell_due(tid, 'anna_01', 0)
    assert not funnel.upsell_due(tid, 'anna_01', 2)
    assert funnel.upsell_due(tid, 'anna_01', 3)
    funnel.apply('давай [INVITE_FRIEND]', tid, 'anna_01', duo=False, user_count=10)
    # right after a fired funnel the block stays out of the prompt
    assert not funnel.upsell_due(tid, 'anna_01', 20)
    cgs.set_guest(tid, 'anna_01', None)


def test_pick_guest_matches_the_app_sheet_and_skips_duOs():
    tid = 777105
    cgs.set_guest(tid, 'anna_01', None)
    guest = funnel.pick_guest(tid, 'anna_01')
    assert guest and guest != 'anna_01'
    assert cgs.can_invite(tid, 'anna_01', guest)
    # an occupied chat has no room for another upsell
    cgs.set_guest(tid, 'anna_01', guest)
    assert funnel.pick_guest(tid, 'anna_01') == ''
    cgs.set_guest(tid, 'anna_01', None)


def test_reply_wires_the_upsell_block_and_the_tag_parser():
    assert 'if not guest_reminder and not scene:' in CHAT
    assert 'invite_funnel.pick_guest(user_id, character_id)' in CHAT
    assert 'invite_funnel.upsell_due(user_id, character_id, _n_user)' in CHAT
    assert 'invite_funnel.upsell_rule(_fn)' in CHAT
    # the tag is stripped BEFORE the answer is saved into history
    apply_at = CHAT.index('invite_funnel.apply(answer, user_id, character_id, duo=duo_chat')
    save_at = CHAT.index('save_message(db_user_id, character_id, "user", user_text)')
    assert apply_at < save_at


def test_bot_delivery_sends_the_teaser_right_after_her_line():
    fn = MAIN[MAIN.index('async def send_answer('):MAIN.index('async def _send_answer_body(')]
    assert 'invite_funnel.take_pending(message.from_user.id, character_id)' in fn
    assert '_send_duo_teaser(message.chat.id, message.from_user.id, character_id, guest_id)' in fn


def test_app_delivery_flips_the_pill_and_shows_the_blur_teaser():
    assert "funnel_guest = invite_funnel.take_pending(telegram_id, character_id)" in MAIN
    assert "payload['guest'] = {'id': funnel_guest," in MAIN
    assert "payload['duo_offer'] = True" in MAIN
    assert "payload['duo_tease'] = tease['duo_tease']" in MAIN
    # the SPA flips the duo pill the moment the reply carries the new guest
    assert 'if (j.guest && CHAT) { CHAT.duo = j.guest.name; CHAT.guest = j.guest; renderGuest(CHAT.id, j.guest, true); }' in INDEX


def test_call_never_speaks_the_tag_aloud():
    # V3.151.0: the spoken text is her MESSAGE block only (never «THOUGHT:»),
    # and the funnel tag is stripped out of it before the call reads it aloud.
    assert 'voice_call.spoken(invite_funnel.strip_tag(message_block(answer)))' in MAIN