# V3.158.0 — «чей тап, тот и платит».
#
# Дамп production-базы от 13.11 показал: 12 ноября привязка расходов к людям
# работала ровно наполовину. Mini App-эндпоинты, которые тратят деньги (трофеи,
# живые ситуации, спон-фото, подарки, озвучка), метку не ставили, а пуши
# планировщика живут в его задаче и вообще не знают, для кого пишут. Дальше по
# дампу видно: у «Её жизни без тебя» 112 строк расхода и ноль владельцев.
#
# Правка: одна метка на входе в приложение (middleware по подписанному
# Telegram initData) плюс метка там, где планировщик тратит деньги конкретного
# человека. Никаких новых таблиц — только строки, которые уже пишутся.

import asyncio
import hashlib
import hmac
import json
import time
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]

from config import TELEGRAM_TOKEN
from services import spend_service
from services import webapp_service


def _signed_init_data(telegram_id: int) -> str:
    """Настоящий HMAC initData — не заглушка парсера: middleware обязан
    принимать то, что принимает сам сервер."""
    pairs = {
        'auth_date': str(int(time.time())),
        'query_id': 'QUERY',
        'user': json.dumps({'id': telegram_id, 'first_name': 'Витя'}),
    }
    check = '\n'.join(f'{k}={v}' for k, v in sorted(pairs.items()))
    secret = hmac.new(b'WebAppData', TELEGRAM_TOKEN.encode(), hashlib.sha256).digest()
    pairs['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(pairs)


def _request(path: str, init_data: str = ''):
    return SimpleNamespace(path=path, query={'init_data': init_data})


async def _run_middleware(path: str, init_data: str) -> int:
    import main

    spend_service.set_spend_user(None)   # чистый контекст: порядок тестов не решает
    seen = {}

    async def handler(request):
        seen['uid'] = spend_service._spend_user.get()
        return 'handled'

    await main._webapp_spend_owner(_request(path, init_data), handler)
    return seen['uid']


# ── приложение: метка до первого потраченного цента ─────────────────────────

def test_the_app_marks_the_owner_before_the_handler_spends():
    # подпись настоящая → id из неё и есть владелец всего хода
    assert asyncio.run(_run_middleware('/webapp/api/trophies/open', _signed_init_data(777001))) == 777001


def test_a_forged_or_missing_init_data_marks_nobody():
    assert asyncio.run(_run_middleware('/webapp/api/trophies/open', 'user=%7B%22id%22%3A1%7D')) == 0
    assert asyncio.run(_run_middleware('/webapp/api/trophies/open', '')) == 0


def test_a_page_without_a_user_does_not_pay_for_the_hmac():
    # статика приложения и чужие пути не должны вообще заходить в метку
    assert asyncio.run(_run_middleware('/webapp', _signed_init_data(777002))) == 0


def test_the_middleware_is_registered_on_the_real_app():
    src = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert 'app.middlewares.append(_webapp_spend_owner)' in src
    block = src[src.index('async def _webapp_spend_owner'):src.index('async def _webapp_api_me')]
    assert "request.path.startswith('/webapp/api/')" in block
    assert 'spend_service.set_spend_user' in block


# ── планировщик: то, что он пишет для конкретного человека ──────────────────

def test_a_life_moment_is_billed_to_the_man_it_is_written_for(monkeypatch):
    from services import life_event_service as les

    seen = {}

    async def boom(*a, **kw):
        seen['uid'] = spend_service._spend_user.get()
        raise AssertionError('стоп: дальше считать не нужно')

    monkeypatch.setattr('services.llm_provider_service.generate_text', boom)
    # момент не должен рассыпаться: проводка проверяется, а генерация — нет
    assert asyncio.run(les.build_life_moment(777003, 'anna_01', 'day')) == {}
    assert seen['uid'] == 777003


def test_the_showcase_voice_is_billed_to_the_one_she_is_singing_to(monkeypatch):
    from services import scheduler_service as ss

    seen = {}

    async def fake_synthesize(text, voice=None, character_id=None, **kw):
        seen['uid'] = spend_service._spend_user.get()
        return b'OGG'

    sent = []

    class FakeBot:
        async def send_voice(self, chat_id, file, **kw):
            sent.append(chat_id)

    monkeypatch.setattr('services.voice_service.synthesize_bytes', fake_synthesize)
    asyncio.run(ss._showcase_voice(FakeBot(), 777004, 'anna_01', 'ru'))
    assert seen['uid'] == 777004
    assert sent == [777004]


def test_the_shared_ritual_stays_ownerless_on_purpose():
    # один голос на день для всех её мужчин: вписывать его первому встречному
    # значит врать в отчёте о том, кто сколько съел
    src = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
    shared = src[src.index('async def _shared_ritual'):src.index('def invalidate_ritual_bundles')]
    assert 'set_spend_user' not in shared


def test_the_spend_ledgers_still_carry_the_user():
    # ничего не сломали: метка middleware — это тот же контекст, что и раньше
    spend_service.set_spend_user(777005)
    spend_service.record_llm_usage('dialogue', 'openrouter', 'm', cost_usd=0.001)
    spend_service.record_image_spend('spicyapi', 'selfie', 0.036)
    spend_service.set_spend_user(None)
    spend_service.record_llm_usage('dialogue', 'openrouter', 'm', cost_usd=0.001)

    from models.app_models import ImageSpend, LlmUsage
    from services.db import SessionLocal
    with SessionLocal() as s:
        rows = s.query(LlmUsage).filter(LlmUsage.telegram_id == 777005).count()
        imgs = s.query(ImageSpend).filter(ImageSpend.telegram_id == 777005).count()
        orphan = s.query(LlmUsage).filter(LlmUsage.telegram_id == 0).count()
    assert rows >= 1 and imgs >= 1 and orphan >= 1


# ── V3.158.1: пульс отношений снова дышит ───────────────────────────────────

def test_the_pulse_reads_the_real_dialog_and_reaches_the_model(monkeypatch):
    from sqlalchemy import select

    from models.relationship_models import UserCharacterRelationship
    from services.db import SessionLocal
    from services.memory_service import save_message
    from services.relationship_pulse import maybe_pulse
    from services.user_service import ensure_user

    tg = 777010
    uid = ensure_user(tg, 'Витя')
    for i in range(6):
        save_message(uid, 'anna_01', 'user', f'устал, но зашёл к тебе, {i}')
        save_message(uid, 'anna_01', 'assistant', f'расскажи, как день, {i}')
    with SessionLocal() as s:
        s.add(UserCharacterRelationship(user_id=uid, character_id='anna_01', total_messages=8))
        s.commit()

    called = {}

    async def fake_generate(messages, **kw):
        called['purpose'] = kw.get('purpose')
        called['excerpt'] = messages[0]['content']

        class R:
            text = '{"warmth":3,"trust":3,"intimacy":2,"events":["care"]}'
            complete = True
        return R()

    monkeypatch.setattr('services.llm_provider_service.generate_text', fake_generate)
    asyncio.run(maybe_pulse(tg, 'Витя', 'anna_01'))

    assert called.get('purpose') == 'relationship_pulse'
    # раньше сюда попадали строки Message, а читали как словари → фрагмент был
    # пустой, и модель не вызывалась никогда
    assert 'Пользователь:' in called['excerpt'] and 'Она:' in called['excerpt']
    with SessionLocal() as s:
        row = s.scalar(select(UserCharacterRelationship).where(
            UserCharacterRelationship.user_id == uid,
            UserCharacterRelationship.character_id == 'anna_01'))
        assert row.trust_score > 0 and row.intimacy_score > 0


def test_the_pulse_is_billed_to_the_man_whose_turn_it_is():
    src = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
    body = src[src.index('async def reply('):src.index('async def proactive_reply')]
    mark = body.index('spend_service.set_spend_user(user_id)')
    pulse = body.index('create_task(maybe_pulse(')
    assert mark < pulse            # задача наследует контекст в момент создания

