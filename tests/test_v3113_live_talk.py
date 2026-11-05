"""V3.113.0: she answers in his rhythm, never bargains, has her own small
stories that go on for days, and pushes lose their template tails."""
from pathlib import Path
import random

from services import live_talk
from services.her_story import STORIES, directive
from services.hook_service import hook_note

ROOT = Path(__file__).resolve().parents[1]
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
PROMPT = (ROOT / 'services' / 'character_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
STATE = (ROOT / 'services' / 'state_service.py').read_text(encoding='utf-8')


def test_rhythm_kinds_and_notes():
    assert live_talk.rhythm_kind('ок') == 'short'
    assert live_talk.rhythm_kind('Как дела') == 'short'
    assert live_talk.rhythm_kind('а ты сегодня что делала после работы?') == 'medium'
    assert live_talk.rhythm_kind('x' * 90) == 'long'
    assert 'коротко' in live_talk.rhythm_note('ок')


def test_fit_rhythm_trims_essay_to_one_word_only():
    essay = 'да нормально, лениво выбираю наряд и уже в предвкушении вечера ✨\n\n' + 'а у тебя как? ' * 12
    assert live_talk.fit_rhythm(essay, 'ок') == 'да нормально, лениво выбираю наряд и уже в предвкушении вечера ✨'
    assert live_talk.fit_rhythm(essay, 'x' * 90) == essay
    short = 'ну норм\n\nа ты?'
    assert live_talk.fit_rhythm(short, 'ок') == short
    sound = 'ох…\n\n' + 'это было неожиданно, правда ' * 10
    assert live_talk.fit_rhythm(sound, 'да').startswith('ох…\n\nэто было')


def test_bargain_detection():
    assert live_talk.bargained_recently(['угадаешь, что на мне — скину фотку'])
    assert live_talk.bargained_recently(['покажу, только условие: сначала ответь'])
    assert live_talk.bargained_recently(['фотку сначала заслужи 💋'])
    assert not live_talk.bargained_recently(['ну привет 🙂', 'я дома, устала'])


def test_leak_detection():
    assert live_talk.looks_leaked('phrasing / formula: "кстати"? Yes.\n    *   Is it in character')
    assert live_talk.looks_leaked('right now (doing, wearing, surroundings), no repeats.\n        *   Detail: sitting')
    assert not live_talk.looks_leaked('ну ты и юркий 😋 засчитываю наполовину')
    assert not live_talk.looks_leaked("Careful, that's exactly how you get me to send another one 💋")


def test_hook_short_and_no_game():
    rng = random.Random(1)
    for _ in range(60):
        _, move = hook_note('flirt', '', True, rng, short=True)
        assert move in ('reaction', 'tease', 'feeling')
        _, move = hook_note('tease', '', True, rng, no_game=True)
        assert move != 'game'


def test_stories_are_well_formed():
    keys = [s.key for s in STORIES]
    assert len(keys) == len(set(keys)) >= 8
    for s in STORIES:
        assert s.setup and s.ask and len(s.outcomes) == 2 and s.after and s.words


def test_her_story_disabled_returns_empty(monkeypatch):
    from services import her_story
    monkeypatch.setattr(her_story, 'ENABLED', False)
    assert directive(1, 1, 'anna_01') == ''


def test_wired_into_reply_and_morning():
    assert 'her_story.directive, db_user_id, user_id, character_id' in CHAT
    assert 'live_talk.rhythm_note(user_text)' in CHAT
    assert 'live_talk.fit_rhythm(answer, user_text)' in CHAT
    assert 'live_talk.looks_leaked(answer)' in CHAT
    assert "finish_or_drop(answer, False, _lang)" in CHAT
    rhythm_at = CHAT.index('live_talk.rhythm_note(user_text)')
    assert rhythm_at < CHAT.index('messages.append({"role": "user", "content": user_text})', rhythm_at)
    assert 'her_story.current, db_user_id, user_id, character_id, start=False' in CHAT


def test_prompt_and_pushes_lose_the_bot_tells():
    assert 'БЕЗ ТОРГА И БЕЗ СПЕКТАКЛЯ' in PROMPT
    assert 'скажешь комплимент — пришлю фотку' not in PROMPT
    assert 'только из душа, волосы мокрые' not in PROMPT
    assert 'не проспи' not in SCHED
    assert 'не прерывай серию' not in SCHED
    assert '_EVENING_PROMISE_RU' in SCHED
    assert 'в тексте не называй одежду' in STATE


MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def _ns():
    import re
    from services.photo_service import PhotoRequest
    ns = {'re': re, 'PhotoRequest': PhotoRequest}
    a = MAIN.index('_HANDS_OVER = re.compile(')
    exec(MAIN[a:MAIN.index('def _accepts_her_photo_offer', a)], ns)
    b = MAIN.index('# V3.113.0: «Покажи сиськи»')
    exec(MAIN[b:MAIN.index('def _free_photo_from_pool', b)], ns)
    return ns


def test_show_me_asks_become_photo_requests():
    ns = _ns()
    f = ns['_show_me_request']
    assert f('Покажи сиськи').scene == 'lingerie'
    assert f('скинь свою жопу').scene == 'personal'
    assert f('покажи себя').scene == 'selfie'
    assert f('Покажи') is None  # bare «покажи» only after her offer
    assert f('покажи мне свой город, где живёшь') is None


def test_bare_hand_over_after_his_ask_counts_as_promise():
    ns = _ns()
    assert ns['_HANDS_OVER'].match('держи 😏 только оцени')
    assert ns['_HANDS_OVER'].match('вот, лови 💋')
    assert ns['_ASKED_TO_SEE'].search('Покажи')
    assert not ns['_HANDS_OVER'].match('я держу кружку')


def test_blocked_photo_comes_with_the_locked_card():
    blocked = MAIN[MAIN.index('def _chat_photo_blocked('):MAIN.index('async def _webapp_chat_turn(')]
    assert "payload['locked_tease']" in blocked
    assert "'free_used', 'premium', 'spicy'" in MAIN
    turn = MAIN[MAIN.index('async def _webapp_chat_turn('):MAIN.index('# V3.90.0: intimacy is Premium-only — his explicit', MAIN.index('async def _webapp_chat_turn('))]
    assert "block in ('peaches', 'premium', 'spicy', 'free_used', 'stage', 'adult')" in turn
    assert 'photo_request = _show_me_request(text)' in turn
