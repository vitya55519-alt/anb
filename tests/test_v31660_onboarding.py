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
    # V3.167.0 §4: к 21 spicy-строке добавились 15 тёплых — романтика больше не
    # «пишет сама из OPENING_SCENES», у неё свой сид.
    assert greeting_service.ensure_seed() == 36
    assert greeting_service.ensure_seed() == 0
    with SessionLocal() as s:
        rows = list(s.scalars(select(CharacterGreeting)))
    assert len([r for r in rows if r.character_id == 'all']) == 30
    personal = {r.character_id for r in rows if r.character_id != 'all'}
    assert personal == {'anna_01', 'kamila_01', 'maria_01', 'liza_01', 'lana_01', 'kira_01'}
    assert all(not r.photo_bytes for r in rows)
    assert {r.mode for r in rows} == {'spicy', 'normal'}
    # V3.166.4 (Блок 4): his personal top-6 cards stay text-only, the universal
    # hooks each carry the hidden English frame behind their chips.
    assert all(not r.image_prompt for r in rows if r.character_id != 'all')
    universal = [r for r in rows if r.character_id == 'all']
    spicy = [r for r in universal if r.mode == 'spicy']
    assert all(r.image_prompt and all(c.isascii() for c in r.image_prompt) for r in spicy)
    assert all(len(json.loads(r.buttons_json)) == 2 for r in universal)
    # every hook ends by asking his consent — to see the frame, or to answer her
    assert all(r.message_text.rstrip().endswith('?') for r in universal)


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
    # ТЗ V3.167.0 §4: романтика больше не пустая — свой тёплый набор, те же два
    # чипа, но без кадра за ними (только тогда её строка не превращается в 18+).
    warm = asyncio.run(greeting_service.opening('anna_01', spicy=False))
    assert warm['text'] and len(warm['buttons']) == 2
    assert warm['starter'] is False and not warm['reply']


def test_both_mode_name_substitution_and_starter_flag():
    greeting_id = greeting_service.create('anna_01', 'both', '{name} ждёт', ['{name}, привет'],
                                          image_prompt='bedroom, dim lighting, lace lingerie')
    opened = asyncio.run(greeting_service.opening('anna_01', spicy=False, name='Анна'))
    assert opened['id'] == greeting_id
    assert opened['text'] == 'Анна ждёт'
    assert opened['buttons'] == ['Анна, привет']
    assert opened['starter'] is True
    # V3.166.4 (Блок 2): the card carries no picture at all — the frame comes
    # only after a chip tap — and its English prompt never leaves the server.
    assert 'photo_url' not in opened and 'photo_file_id' not in opened
    assert 'image_prompt' not in opened
    plain = greeting_service.create('maria_01', 'both', 'Текст без кадра', ['Привет'])
    assert asyncio.run(greeting_service.opening('maria_01', spicy=False))['starter'] is False
    greeting_service.delete(plain)


def test_greeting_endpoint_saves_only_her_line_and_registers_the_tap():
    start = MAIN[MAIN.index('async def _webapp_api_chat_start'):MAIN.index('def _chat_opening_spicy')]
    assert "location='дома / в спальне'" in start
    assert "'assistant', _greeting['text']" in start
    assert "greeting_service.remember_offer" in start
    assert "'chips': _greeting.get('buttons') or []" in start
    # ТЗ V3.167.0 §4: плашка «Раздеть» — дверь в 18+, в тёплом режиме её нет
    assert "'undress_price': EXPLICIT_PHOTO_PEACH_COST if _spicy else 0" in start
    assert "media_kind='photo'" not in start
    assert "app.router.add_get('/webapp/starter/{cache_id}', _webapp_starter_photo)" in MAIN
    assert "_webapp_greeting_photo" not in MAIN


def test_translation_is_paid_once_then_read_from_cache(monkeypatch):
    # V3.166.5 (владелец: «немота»): её слова перед кадром переводятся этим же
    # одним вызовом и лежат в том же кэше — без них тап по чипу ответил бы ему
    # по-русски.
    greeting_service.create('anna_01', 'spicy', 'Иди сюда', ['Подойти', 'Обнять'],
                            reply_text='Я тебя жду')
    calls = []

    async def translate(text, buttons, lang, reply=''):
        calls.append((text, buttons, lang, reply))
        return 'Come here', ['Come closer', 'Hug her'], 'I am waiting for you'

    monkeypatch.setattr(greeting_service, '_translate', translate)
    first = asyncio.run(greeting_service.opening('anna_01', spicy=True, lang='en'))
    second = asyncio.run(greeting_service.opening('anna_01', spicy=True, lang='en'))
    assert len(calls) == 1
    assert first['text'] == second['text'] == 'Come here'
    assert second['buttons'] == ['Come closer', 'Hug her']
    assert second['reply'] == 'I am waiting for you'
    with SessionLocal() as s:
        cached = json.loads(s.scalar(select(CharacterGreeting.translations_json)))
    assert cached['en']['text'] == 'Come here'
    assert cached['en']['reply'] == 'I am waiting for you'


def test_owner_kitchen_has_the_four_step_card_flow():
    wizard = MAIN[MAIN.index('GREETING_WAIT: dict[int, dict] = {}'):MAIN.index('def admin_badges_keyboard')]
    assert "text='💌 Стартовые сообщения" in MAIN
    # V3.166.4: her line → chips → the hidden English frame. The photo step is
    # gone with the card pictures, and so is the bot's photo download.
    # V3.166.5 added the fourth: what she writes right before that frame.
    assert "'step': 'text'" in wizard
    assert "state['step'] = 'buttons'" in wizard
    assert "state['step'] = 'prompt'" in wizard
    assert "state['step'] = 'reply'" in wizard
    assert "'step': 'photo'" not in wizard
    assert "state['photo_bytes'] = buf.getvalue()" not in wizard
    assert "image_prompt=prompt, reply_text=reply)" in wizard
    assert "if cq.from_user.id not in ADMIN_TELEGRAM_IDS" in MAIN


def test_vertical_cards_scenario_chips_and_standard_paid_flow():
    css = INDEX[INDEX.index('#modeScreen .cards'):INDEX.index('#modeScreen .ms-note')]
    # V3.166.2 (Блок 1): full-bleed 3:4 cards, one under another, caption on the
    # bottom edge over the tall gradient — the owner's shot fills the card and a
    # 3:4 box crops nothing of an 864x1152 picture.
    assert 'grid-template-columns: 1fr;' in css
    assert 'aspect-ratio: 3 / 4' in css
    assert 'linear-gradient(to top, rgba(0,0,0,.9) 0%, rgba(0,0,0,.7) 40%, rgba(0,0,0,0) 100%)' in css
    assert 'padding: 18px' in css and 'text-align: left' in css
    # the hierarchy he asked for: 23px/800 white title, 14.5px/500 soft-white bullets
    assert 'font-size: 23px' in css and 'font-weight: 800' in css
    assert 'font-size: 14.5px' in css and 'line-height: 1.4' in css
    assert 'class="shade"' in INDEX and '<span class="bl">' in INDEX
    # V3.166.2 (Блок 2): the exact bullet copy, the ceiling number from the server
    assert "ms_normal_b: n => ['Лёгкий флирт, свидания и долгие разговоры.'," in INDEX
    assert "'Покори её сердце, и она ответит взаимностью.'," in INDEX
    assert "ms_spicy_b: n => ['Воплощение любых твоих фантазий.'," in INDEX
    assert "'Откровенные фото по твоим сценариям.'," in INDEX
    assert "n + ' сообщений в день (с Premium — безлимит).'" in INDEX
    assert 'ME.chat_cap' in INDEX
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
