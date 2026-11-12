"""V3.148.0 — owner ТЗ of 12 Nov 2026: /start ➔ 18+ ➔ one button into the app.

1. The start gate carries two buttons: «Мне 18+ · принимаю условия» and the
   WebApp tile. Nothing else.
2. The 18+ tap rewrites that same bubble («Добро пожаловать» + the app button) —
   no menu message, no girl picker, no pinned line, no reply keyboard.
3. She stays silent until he opens her chat and writes the first message:
   the auto-hello, the welcome selfie and the app-side greeting seed are gone.
4. The welcome media is the owner's gif again.
"""
import asyncio
import datetime
import os
from pathlib import Path

os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake-token-for-static-tests-only')
os.environ.setdefault('GEMINI_API_KEY', 'x')

import pytest
from aiogram import types

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
UI = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')

APP_BASE = 'https://example.test'
APP_URL = f'{APP_BASE}/webapp'


def _use_app(monkeypatch):
    import main
    monkeypatch.setattr(main, 'PUBLIC_BASE_URL', APP_BASE)
    return main


def _gate(main, lang):
    return main.consent_keyboard(lang).inline_keyboard


# ── 1. the gate ────────────────────────────────────────────────────────────
def test_the_gate_is_18_plus_and_the_app_and_nothing_else(monkeypatch):
    main = _use_app(monkeypatch)
    rows = _gate(main, 'ru')
    assert len(rows) == 2
    assert rows[0][0].callback_data == 'consent:accept'
    assert rows[1][0].web_app.url == APP_URL
    assert rows[1][0].text == '📱 Открыть приложение'
    # V3.148.0: terms/privacy left the gate — the 18+ label carries the
    # acceptance and /legal keeps the documents reachable.
    assert 'consent:terms' not in str(rows)
    assert 'consent:privacy' not in str(rows)


def test_the_app_button_is_localized_for_every_app_language(monkeypatch):
    from services.ui_lang import APP_LANGS, flow_text
    main = _use_app(monkeypatch)
    for lang in APP_LANGS:
        rows = _gate(main, lang)
        assert rows[1][0].text == flow_text(lang, 'open_app'), lang
        assert rows[1][0].web_app.url == APP_URL, lang


# ── 2. the tap rewrites the bubble ─────────────────────────────────────────
def _cq(animation: bool):
    user = types.User(id=777001, is_bot=False, first_name='Test', language_code='ru')
    bot_user = types.User(id=1, is_bot=True, first_name='bot')
    chat = types.Chat(id=777001, type='private')
    fields = {'message_id': 11, 'date': datetime.datetime.now(tz=datetime.timezone.utc),
              'chat': chat, 'from_user': bot_user}
    if animation:
        fields['animation'] = types.Animation(file_name='welcome.gif', mime_type='image/gif',
                                              file_id='fid', file_unique_id='fuw',
                                              duration=2, width=692, height=388)
    else:
        fields['text'] = 'Что умеет этот бот?'
    msg = types.Message(**fields)
    return types.CallbackQuery(id='1', from_user=user, chat_instance='x', message=msg,
                               data='consent:accept')


@pytest.fixture
def funnel(monkeypatch):
    main = _use_app(monkeypatch)
    sent = []

    async def _noop(*a, **k):
        return None

    async def _answer(self, *a, **k):
        sent.append(('answer', a, k))

    async def _edit_text(self, **k):
        sent.append(('edit_text', k))

    async def _edit_caption(self, **k):
        sent.append(('edit_caption', k))

    class _Lock:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(types.Message, 'answer', _answer)
    monkeypatch.setattr(types.Message, 'edit_text', _edit_text)
    monkeypatch.setattr(types.Message, 'edit_caption', _edit_caption)
    monkeypatch.setattr(types.CallbackQuery, 'answer', _noop)
    monkeypatch.setattr(main, 'accept_consent', lambda tg: None)
    monkeypatch.setattr(main, 'set_adult_confirmed', lambda tg, v: None)
    monkeypatch.setattr(main, 'track_event', lambda *a, **k: None)
    monkeypatch.setattr(main, 'ensure_user', lambda *a, **k: 1)
    monkeypatch.setattr(main, 'referral_user_lock', lambda tg: _Lock())
    monkeypatch.setattr(main, 'pending_referral', lambda tg: None)
    monkeypatch.setattr(main, 'apply_first_start_bonuses',
                        lambda tg: {'credits': 200, 'trial_days': 0})
    monkeypatch.setattr(main, 'full_user_lang', lambda tg, code: 'ru')
    return main, sent


def test_the_tap_rewrites_the_media_bubble(funnel):
    main, sent = funnel
    asyncio.run(main.consent_accept(_cq(animation=True)))
    assert len(sent) == 1
    kind, kw = sent[0]
    assert kind == 'edit_caption'
    assert kw['caption'] == '🎁 Добро пожаловать! Тебе начислено 200 фото-кредитов 👇'
    rows = kw['reply_markup'].inline_keyboard
    assert len(rows) == 1 and rows[0][0].web_app.url == APP_URL


def test_the_tap_rewrites_a_plain_text_bubble(funnel):
    main, sent = funnel
    asyncio.run(main.consent_accept(_cq(animation=False)))
    assert [k for k, _ in sent] == ['edit_text']
    assert sent[0][1]['text'].startswith('🎁 Добро пожаловать!')


def test_the_tap_never_stacks_a_second_message(funnel):
    main, sent = funnel
    asyncio.run(main.consent_accept(_cq(animation=True)))
    # the edit is the whole answer: no menu bubble, no picker, no greeting,
    # no photo, no reply keyboard
    assert not [s for s in sent if s[0] == 'answer']
    start = MAIN.index('async def consent_accept(')
    body = MAIN[start:MAIN.index("@dp.callback_query(F.data == 'consent:terms')")]
    assert 'reply_markup=main_keyboard(' not in body
    assert 'send_photo' not in body


# ── 3. silence until he writes ─────────────────────────────────────────────
def test_no_auto_greeting_survives_anywhere():
    for name in ('_deliver_first_hello', '_first_hello_fallback', '_ensure_webapp_first_hello',
                 '_send_welcome_selfie', 'first_reply_cb', 'pick_girl_cb', '_picker_rows',
                 '_PICKER_GIRLS', 'girl_picker_shown', 'welcome_selfie_sent', 'first_hello_sent'):
        assert name not in MAIN, name
    assert MAIN.count('asyncio.sleep(120)') == 0


def test_the_picker_buttons_left_the_chat():
    assert "callback_data='credits:open'" not in MAIN[MAIN.index('def _app_row('):MAIN.index('def _start_keyboard(')]
    assert "callback_data='partner:open'" not in MAIN[MAIN.index('def _app_row('):MAIN.index('def _start_keyboard(')]
    assert 'kb_label' not in MAIN[MAIN.index('def _app_row('):MAIN.index('def _start_keyboard(')]


def test_the_start_copy_no_longer_asks_for_a_girl():
    assert "'welcome_edit'" in UI and "'welcome_edit_plain'" in UI and "'open_app'" in UI
    assert "'start_pick'" not in UI
    assert 'С кем хочешь познакомиться?' not in UI
    assert "'picker_anna_01'" not in UI


# ── 4. the media is the owner's gif ────────────────────────────────────────
def test_the_gif_is_the_welcome_media_again():
    fn = MAIN[MAIN.index('def _welcome_banner_file('):MAIN.index('_welcome_gif_file_id = ')]
    assert fn.index('if WELCOME_BANNER_GIF_PATH.exists():') < fn.index('WELCOME_BANNER_EN_PATH.exists()')
    assert 'WELCOME_PORTRAIT_PATH' not in MAIN
    assert not (ROOT / 'data' / 'media' / 'welcome_portrait.jpg').exists()
