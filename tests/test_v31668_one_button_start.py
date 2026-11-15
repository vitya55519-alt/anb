"""V3.166.8 — owner's screen of 15 Nov 2026: the first bubble has ONE button.

1. /start no longer asks for the 18+ tap: the bubble carries the app door and
   nothing else.
2. The bot writes the consent and the adult flag itself at that first /start —
   without them the several dozen `has_accepted` / `is_adult_confirmed` gates
   would send a newcomer «подтверди 18+ в чате бота» with no button left.
3. The bonuses land at the same moment, under the same per-user lock.
4. `consent_keyboard` stays for the legacy bubbles and the fallback branches —
   a user who arrived here without consent must still have a way out.
"""
import asyncio
import datetime
import os
from pathlib import Path

os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake-token-for-static-tests-only')
os.environ.setdefault('GEMINI_API_KEY', 'x')

import pytest
from aiogram import types
from aiogram.filters import CommandObject

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')

APP_BASE = 'https://example.test'
APP_URL = f'{APP_BASE}/webapp'


class _Lock:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


async def _noop(*a, **k):
    return None


def _start_message(uid: int = 777902, lang: str = 'ru'):
    user = types.User(id=uid, is_bot=False, first_name='Test', language_code=lang)
    return types.Message(
        message_id=21, date=datetime.datetime.now(tz=datetime.timezone.utc),
        chat=types.Chat(id=uid, type='private'), from_user=user, text='/start')


@pytest.fixture
def fresh_start(monkeypatch):
    import main
    monkeypatch.setattr(main, 'PUBLIC_BASE_URL', APP_BASE)
    seen = {'consent': [], 'adult': [], 'banner': None}
    monkeypatch.setattr(main, 'has_accepted', lambda tg: False)
    monkeypatch.setattr(main, 'accept_consent', lambda tg: seen['consent'].append(tg))
    monkeypatch.setattr(main, 'set_adult_confirmed', lambda tg, v: seen['adult'].append((tg, v)))
    monkeypatch.setattr(main, 'track_event', lambda *a, **k: None)
    monkeypatch.setattr(main, 'ensure_user', lambda *a, **k: 1)
    monkeypatch.setattr(main, 'referral_user_lock', lambda tg: _Lock())
    monkeypatch.setattr(main, 'pending_referral', lambda tg: None)
    monkeypatch.setattr(main, 'apply_first_start_bonuses',
                        lambda tg: {'credits': 200, 'trial_days': 0})
    monkeypatch.setattr(main, 'user_lang', lambda tg: 'ru')
    monkeypatch.setattr(main, 'parse_referral_payload', lambda a: None)
    monkeypatch.setattr(main, 'parse_source_payload', lambda a: (None, None))
    monkeypatch.setattr(main, 'set_source', lambda *a, **k: False)
    monkeypatch.setattr(main, 'remember_referral', lambda *a, **k: None)

    async def _banner(msg, lang, caption, markup):
        seen['banner'] = (lang, caption, markup)

    monkeypatch.setattr(main, '_send_welcome_banner', _banner)
    monkeypatch.setattr(main.chat_hygiene, 'open_screen', _noop)
    monkeypatch.setattr(main.chat_hygiene, 'close_screen', lambda token: None)
    return main, seen


# ── 1. one button ──────────────────────────────────────────────────────────
def test_the_start_keyboard_is_the_app_door_and_nothing_else(monkeypatch):
    import main
    monkeypatch.setattr(main, 'PUBLIC_BASE_URL', APP_BASE)
    rows = main.start_keyboard('ru').inline_keyboard
    assert len(rows) == 1
    assert rows[0][0].web_app.url == APP_URL
    assert rows[0][0].text == '📱 Открыть приложение'
    assert 'consent:accept' not in str(rows)


def test_the_app_door_is_localized_for_every_app_language(monkeypatch):
    from services.ui_lang import APP_LANGS, flow_text
    import main
    monkeypatch.setattr(main, 'PUBLIC_BASE_URL', APP_BASE)
    for lang in APP_LANGS:
        rows = main.start_keyboard(lang).inline_keyboard
        assert len(rows) == 1, lang
        assert rows[0][0].text == flow_text(lang, 'open_app'), lang


def test_first_start_shows_the_single_button(fresh_start):
    main, seen = fresh_start
    asyncio.run(main.start(_start_message(), CommandObject()))
    lang, caption, markup = seen['banner']
    assert lang == 'ru'
    assert [r[0].text for r in markup.inline_keyboard] == ['📱 Открыть приложение']


# ── 2. the bot signs for him ───────────────────────────────────────────────
def test_first_start_records_consent_and_adult_itself(fresh_start):
    main, seen = fresh_start
    asyncio.run(main.start(_start_message(), CommandObject()))
    assert seen['consent'] == [777902]
    assert seen['adult'] == [(777902, True)]


def test_the_start_copy_stops_asking_for_confirmation():
    start = MAIN[MAIN.index('if not has_accepted(message.from_user.id):'):
                 MAIN.index('# Returning user who already accepted')]
    for gone in ('Подтверди, что тебе 18+', 'after confirming 18+', 'после подтверждения 18+',
                 'Confirm you are 18+', 'accept the terms of use'):
        assert gone not in start, gone
    # the features line and the CTA stay — only the ask is gone
    assert 'Идеальная девушка на вечер' in start
    assert '⬇️ Поехали! ⬇️' in start
    assert '⬇️ Let’s go! ⬇️' in start
    assert 'start_keyboard(lang)' in start


# ── 3. the bonus still lands on the first start ────────────────────────────
def test_first_start_grants_the_bonus_under_the_lock(fresh_start, monkeypatch):
    main, seen = fresh_start
    granted = []
    monkeypatch.setattr(main, 'apply_first_start_bonuses',
                        lambda tg: granted.append(tg) or {'credits': 200, 'trial_days': 0})
    asyncio.run(main.start(_start_message(), CommandObject()))
    assert granted == [777902]
    assert '🎁' in seen['banner'][1]


# ── 4. the way out for a user without consent stays alive ──────────────────
def test_consent_keyboard_survives_for_the_legacy_branches():
    assert 'def consent_keyboard(' in MAIN
    assert MAIN.count('reply_markup=consent_keyboard(') >= 4
    assert "@dp.callback_query(F.data == 'consent:accept')" in MAIN
