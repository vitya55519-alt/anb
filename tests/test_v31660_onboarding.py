import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from models.app_models import Base, CharacterGreeting
from services import character_service, greeting_service
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


@pytest.fixture(autouse=True)
def clean_greetings():
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.execute(delete(CharacterGreeting))
        s.commit()
    yield
    with SessionLocal() as s:
        s.execute(delete(CharacterGreeting))
        s.commit()


def test_seed_has_six_personal_and_fifteen_universal_cards_and_is_idempotent():
    assert greeting_service.ensure_seed() == 21
    assert greeting_service.ensure_seed() == 0
    with SessionLocal() as s:
        rows = list(s.scalars(select(CharacterGreeting)))
    assert len([r for r in rows if r.character_id == 'all']) == 15
    personal = {r.character_id for r in rows if r.character_id != 'all'}
    assert personal == {'anna_01', 'kamila_01', 'maria_01', 'liza_01', 'lana_01', 'kira_01'}
    assert all(r.mode == 'spicy' and not r.photo_bytes for r in rows)
    massage = next(r for r in rows if 'массажное масло' in r.message_text)
    assert json.loads(massage.buttons_json) == ['Начать массаж', 'Капнуть масло на поясницу']


def test_seed_does_not_duplicate_or_replace_the_owners_rows():
    greeting_service.create('anna_01', 'normal', 'Моя карточка', ['Привет'])
    assert greeting_service.ensure_seed() == 0
    assert greeting_service.list_for('anna_01')[0]['text'] == 'Моя карточка'


def test_opening_uses_heroine_then_universal_and_keeps_normal_fallback():
    greeting_service.ensure_seed()
    personal = asyncio.run(greeting_service.opening('anna_01', spicy=True))
    universal = asyncio.run(greeting_service.opening('unknown_01', spicy=True))
    assert 'панорамного окна' in personal['text']
    assert universal['text'] and len(universal['buttons']) == 2
    assert asyncio.run(greeting_service.opening('anna_01', spicy=False)) is None


def test_both_mode_name_substitution_and_photo_url():
    greeting_id = greeting_service.create(
        'anna_01', 'both', '{name} ждёт', ['{name}, привет'],
        photo_file_id='telegram-file', photo_bytes=b'jpeg-bytes')
    opened = asyncio.run(greeting_service.opening('anna_01', spicy=False, name='Анна'))
    assert opened['id'] == greeting_id
    assert opened['text'] == 'Анна ждёт'
    assert opened['buttons'] == ['Анна, привет']
    assert opened['photo_url'] == f'/webapp/greeting/{greeting_id}'
    assert opened['photo_file_id'] == 'telegram-file'
    assert greeting_service.photo_for(greeting_id) == b'jpeg-bytes'


def test_translation_is_paid_once_then_read_from_cache(monkeypatch):
    greeting_service.create('anna_01', 'spicy', 'Иди сюда', ['Подойти', 'Обнять'])
    calls = []

    async def translate(text, buttons, lang):
        calls.append((text, buttons, lang))
        return 'Come here', ['Come closer', 'Hug her']

    monkeypatch.setattr(greeting_service, '_translate', translate)
    first = asyncio.run(greeting_service.opening('anna_01', spicy=True, lang='en'))
    second = asyncio.run(greeting_service.opening('anna_01', spicy=True, lang='en'))
    assert len(calls) == 1
    assert first['text'] == second['text'] == 'Come here'
    assert second['buttons'] == ['Come closer', 'Hug her']
    with SessionLocal() as s:
        cached = json.loads(s.scalar(select(CharacterGreeting.translations_json)))
    assert cached['en']['text'] == 'Come here'


def test_greeting_endpoint_saves_her_line_and_photo_before_returning():
    start = MAIN[MAIN.index('async def _webapp_api_chat_start'):MAIN.index('def _chat_opening_spicy')]
    assert "location='дома / в спальне'" in start
    assert "'assistant', _greeting['text']" in start
    assert "media_kind='photo', media_url=_greeting['photo_url']" in start
    assert "'chips': _greeting.get('buttons') or []" in start
    assert "'undress_price': EXPLICIT_PHOTO_PEACH_COST" in start
    assert "app.router.add_get('/webapp/greeting/{greeting_id}', _webapp_greeting_photo)" in MAIN


def test_owner_kitchen_has_the_three_step_card_flow():
    assert "text='💌 Стартовые сообщения'" in MAIN
    assert "'step': 'photo'" in MAIN
    assert "state['step'] = 'text'" in MAIN
    assert "state['step'] = 'buttons'" in MAIN
    assert "state['photo_file_id'] = message.photo[-1].file_id" in MAIN
    assert "state['photo_bytes'] = buf.getvalue()" in MAIN
    assert "if cq.from_user.id not in ADMIN_TELEGRAM_IDS" in MAIN


def test_vertical_cards_scenario_chips_and_standard_paid_flow():
    assert 'aspect-ratio: 3 / 4' in INDEX
    assert 'linear-gradient(' in INDEX[INDEX.index('.modecard .shade'):INDEX.index('.modecard .txt')]
    assert "ms_normal_t: 'Романтика и флирт'" in INDEX
    assert "ms_spicy_t: 'Без цензуры 18+'" in INDEX
    assert "ms_normal_t: 'Romance & flirting'" in INDEX
    assert "ms_spicy_t: 'Uncensored 18+'" in INDEX
    assert 'renderChatHints(data && data.chips, data && data.undress_price)' in INDEX
    assert "opener_undress: n => '🔥 Раздеться · ' + peachNum(n) + ' 🍑'" in INDEX
    assert "undress.addEventListener('click', () => openHot18(CHAT))" in INDEX


def test_prompt_bans_unprompted_health_and_household_complaints():
    prompt = character_service.build_system_prompt(
        {'name': 'Анна', 'age': 26, 'personality': {}}, '', [])
    assert 'НИКОГДА не жалуйся на здоровье, усталость или бытовые проблемы' in prompt
    assert 'Держи страстный, игривый тон и провоцируй пользователя на действия.' in prompt
    assert 'Если устала — скажи это' not in prompt
