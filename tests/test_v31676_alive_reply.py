"""V3.167.6 (владелец, скрин 16.11): откровенный ход не должен кончаться
«Не получилось ответить — попробуй ещё раз».

Цензура провайдера на 18+ тексте поднимает RuntimeError из цепочки, и весь ход
падал: в Mini App это 502 {'ok': False, 'error': 'reply'}, то есть мёртвая
плашка вместо её строки. Теперь отказ провайдера — это пустой ответ, а пустой
ответ у неё уже был отработан: запасная живая фраза, диалог продолжается.
"""
import asyncio
import logging
from types import SimpleNamespace

import services.chat_service as cs
from services.chat_service import STALL_LINES_RU, _gen
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
    assert answer in STALL_LINES_RU, answer


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
