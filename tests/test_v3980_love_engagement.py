"""V3.98.0 — engagement pack from the 3 Nov 2026 stats review.

- she answers in the language he writes in (14% of replies to English were Russian);
- a new user picks "his" girl in the first minute (64 of 92 stayed with the default);
- a failed chat photo falls back to a ready photo of her instead of «не загрузилось».
"""
from pathlib import Path

from services import lang_guard

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')


def test_english_detected():
    assert lang_guard.looks_english('Send a video')
    assert lang_guard.looks_english('show me more')
    assert lang_guard.looks_english('hmm', 'en')
    assert lang_guard.looks_english('mm', recent_user_texts=['I want you', 'ok'])


def test_russian_and_layout_gibberish_not_english():
    assert not lang_guard.looks_english('привет, как дела?')
    assert not lang_guard.looks_english('Hello привет')
    assert not lang_guard.looks_english('ltgkjq')          # «деплой» in EN layout
    assert not lang_guard.looks_english('ghbdtn xnj cltkftim')
    assert not lang_guard.looks_english('hmm', 'ru')
    assert not lang_guard.looks_english('')


def test_cyrillic_dominant():
    assert lang_guard.is_cyrillic_dominant('видео не выйдет 😏 хочешь вечером?')
    assert not lang_guard.is_cyrillic_dominant("I can't do video now 😏 wanna see a sunset?")
    assert not lang_guard.is_cyrillic_dominant('ok')


def test_chat_service_wires_language_guard():
    # V3.117.0: generalized from English to any language he writes in
    assert 'lang_guard.detect_lang(' in CHAT
    assert 'lang_guard.directive(lang)' in CHAT
    assert 'lang_guard.strict_directive(lang)' in CHAT
    # the directive goes right before his message
    assert CHAT.index('lang_guard.directive(lang)') < CHAT.index('messages.append({"role": "user", "content": user_text})')


def test_the_start_picker_and_its_fallback_are_gone():
    # V3.98.0 put a girl picker behind consent; the V3.148.0 ТЗ moved the whole
    # choice into the Mini App, so the picker, its 2-minute hello fallback and
    # the picker analytics event are out of the bot.
    assert 'def _start_keyboard(' in MAIN
    assert 'def _picker_rows(' not in MAIN
    assert "F.data.startswith('pickgirl:')" not in MAIN
    assert 'async def _first_hello_fallback(' not in MAIN
    assert 'girl_picker_shown' not in MAIN
    assert MAIN.count('asyncio.sleep(120)') == 0


def test_the_heroines_still_resolve():
    from services.character_registry import get_character
    for cid in ('agata_01', 'anna_01', 'alisa_01', 'kamila_01', 'rita_01'):
        assert get_character(cid)


def test_flow_text_has_every_app_language():
    from services.ui_lang import APP_LANGS, FLOW_TEXT, flow_text

    keys = set(FLOW_TEXT['en'])
    for lang in APP_LANGS:
        assert set(FLOW_TEXT[lang]) == keys
        assert '{' not in flow_text(lang, 'welcome_edit', amount=200)
        assert flow_text(lang, 'welcome_edit_plain')
        assert flow_text(lang, 'open_app')
        assert flow_text(lang, 'gift_text', amount=300)
        assert flow_text(lang, 'girl_of_day', name='Anna').endswith('Anna')


def test_failed_photo_falls_back_to_pool_without_charge():
    assert "'photo_fallback_pool'" in MAIN
    assert 'not spicy_needs_premium(PhotoRequest(scene=scene))' in MAIN
    assert 'if telegram_id not in ADMIN_TELEGRAM_IDS and not fallback:' in MAIN
