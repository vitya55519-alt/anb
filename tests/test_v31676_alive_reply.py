"""V3.167.6 (владелец, скрин 16.11): откровенный ход не должен кончаться
«Не получилось ответить — попробуй ещё раз».

Цензура провайдера на 18+ тексте поднимает RuntimeError из цепочки, и весь ход
падал: в Mini App это 502 {'ok': False, 'error': 'reply'}, то есть мёртвая
плашка вместо её строки. Теперь отказ провайдера — это пустой ответ, а пустой
ответ в V3.167.1 закрывает одна нейтральная заглушка про связь: диалог
продолжается, и в историю она не пишется.
"""
import asyncio
import logging
from types import SimpleNamespace

import services.chat_service as cs
from services.chat_service import STUB_REPLY_RU, _gen
from services.user_service import ensure_user
from services.memory_service import save_message

logging.getLogger('services.llm_provider_service').setLevel(logging.CRITICAL)

ROOT = cs.__file__
CHAT = open(ROOT, encoding='utf-8').read()

TID = 559001


def _seed(n: int = 8, tid: int = TID, name: str = 'alive') -> int:
    """History long enough to step over the scripted onboarding demo (5th/7th)."""
    uid = ensure_user(tid, name, language_code='ru')
    for i in range(n):
        save_message(uid, 'anna_01', 'user', f'привет {i}')
    return uid


def _res(text: str):
    return SimpleNamespace(text=text, provider='test', model='test', complete=True)


def _patch(monkeypatch, fail_purposes, answer='да, и очень хочу 🙈'):
    seen = []

    async def fake(messages, **kw):
        purpose = kw.get('purpose')
        seen.append(purpose)
        if purpose in fail_purposes:
            raise RuntimeError('LLM unavailable: MiniMax: content blocked')
        return _res(answer)

    monkeypatch.setattr(cs, 'generate_text', fake)
    return seen


def test_dialogue_crash_answers_instead_of_dying(monkeypatch):
    _seed()
    seen = _patch(monkeypatch, {'dialogue'})
    answer = asyncio.run(cs.reply(TID, 'alive', 'ты хочешь сосать мне хуй?', language_code='ru'))
    assert seen, 'the dialogue call was attempted'
    assert (answer or '').strip(), 'he must get her line, not an empty reply'
    assert answer == STUB_REPLY_RU, answer


def test_rewrite_crash_keeps_her_own_words(monkeypatch):
    _seed(tid=559002, name='rewrite')
    _patch(monkeypatch, {'rewrite'}, answer='мм давай ближе 🔥')
    answer = asyncio.run(cs.reply(559002, 'rewrite', 'подойди ближе', language_code='ru'))
    assert 'ближе' in answer


def test_refusal_recovery_crash_declines_in_her_voice(monkeypatch):
    _seed(tid=559003, name='refusal')
    _patch(monkeypatch, {'rewrite'}, answer='такого рода ролевые игры я не поддерживаю')
    answer = asyncio.run(cs.reply(559003, 'refusal', 'расскажи про это', language_code='ru'))
    assert (answer or '').strip()
    assert 'не поддерживаю' not in answer


def test_gen_helper_returns_an_empty_result():
    async def boom(messages, **kw):
        raise RuntimeError('LLM unavailable: no providers')

    original = cs.generate_text
    cs.generate_text = boom
    try:
        out = asyncio.run(_gen([{'role': 'user', 'content': 'x'}], max_tokens=10, purpose='dialogue'))
    finally:
        cs.generate_text = original
    assert out.text == ''
    assert out.provider == 'failed'


def test_dialogue_sites_go_through_the_guard():
    # ни один из трёх ходов, которые читает он, не зовёт цепочку напрямую
    assert 'r = await _gen(messages, max_tokens=token_budget' in CHAT
    assert 'r = await _gen(rewrite_messages' in CHAT
    assert 'r = await _gen(\n        [{"role": "system", "content": _refusal_rewrite_instructions' in CHAT
    assert 'r = await generate_text(messages, max_tokens=token_budget' not in CHAT


def test_app_turn_never_returns_the_dead_error(monkeypatch):
    import main

    _seed(tid=559004, name='appturn')
    _patch(monkeypatch, {'dialogue'})
    main.set_adult_confirmed(559004, True)
    resp = asyncio.run(main._webapp_chat_turn(
        559004, {'first_name': 'appturn', 'language_code': 'ru'}, 'anna_01',
        'ты хочешь сосать мне хуй?'))
    assert resp.status == 200, resp.body
    assert b'"ok": true' in resp.body


def test_app_turn_bounces_when_the_whole_turn_dies(monkeypatch):
    """Не только ИИ: любой сбой хода в Mini App теперь её живая строка, а не
    мёртвая плашка «Не получилось ответить»."""
    import main

    _seed(tid=559005, name='bounce')
    main.set_adult_confirmed(559005, True)

    async def boom(*a, **kw):
        raise RuntimeError('PostgreSQL is down')

    sent = []

    async def _no_send(*a, **kw):
        sent.append(a)

    monkeypatch.setattr(main, 'anna_reply', boom)
    monkeypatch.setattr(main.bot, 'send_message', _no_send)
    resp = asyncio.run(main._webapp_chat_turn(
        559005, {'first_name': 'bounce', 'language_code': 'ru'}, 'anna_01', 'привет'))
    assert resp.status == 200, resp.body
    assert b'"fallback": true' in resp.body


def test_failure_notice_is_redacted_and_once_a_minute(monkeypatch):
    import main

    main._turn_fail_at.clear()
    sent = []

    async def capture(chat_id, text, **kw):
        sent.append((chat_id, text))

    monkeypatch.setattr(main.bot, 'send_message', capture)
    monkeypatch.setattr(main, 'ADMIN_TELEGRAM_IDS', {9001})
    asyncio.run(main._notify_turn_failure(559006, 'ход чата в Mini App',
                                          RuntimeError('upstream sk-ABCDEFGHIJKLMNOPQRSTUVWX')))
    assert len(sent) == 1
    text = sent[0][1]
    assert 'RuntimeError' in text and 'ход чата' in text
    assert 'ABCDEFGHIJKLMNOPQRSTUVWX' not in text
    asyncio.run(main._notify_turn_failure(559006, 'ход чата в Mini App', RuntimeError('ещё')))
    assert len(sent) == 1, 'второго сообщения в ту же минуту нет'

