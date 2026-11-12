"""V3.117.0 — she talks in his language (Bengali and others), Bengali UI,
foreign shop in English with Stars first. Russian talks stay Russian."""
from pathlib import Path

from services import lang_guard as g
from services.dialogue_guard_service import finish_or_drop

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')


def test_russian_stays_russian():
    assert g.detect_lang('привет, как дела?') == 'ru'
    assert g.detect_lang('привет', 'bn', (), 'bn') == 'ru'      # Cyrillic always wins
    assert g.detect_lang('ltgkjq', 'ru') == 'ru'                # layout gibberish
    assert g.detect_lang('ghbdtn xnj cltkftim', 'ru') == 'ru'
    assert g.detect_lang('😍', 'en') == 'ru'                    # Russian with EN Telegram
    assert g.detect_lang('😍', 'ru', ['как ты?']) == 'ru'
    assert g.detect_lang('ai girl') == 'ru'


def test_scripts_detected():
    assert g.detect_lang('আমি তোমাকে ভালোবাসি') == 'bn'
    assert g.detect_lang('नमस्ते') == 'hi'
    assert g.detect_lang('こんにちは') == 'ja'
    assert g.detect_lang('你好') == 'zh'
    assert g.detect_lang('안녕') == 'ko'


def test_latin_languages():
    assert g.detect_lang('Send a video') == 'en'
    assert g.detect_lang('hola guapa, cómo estás') == 'es'
    assert g.detect_lang('ciao bella') == 'it'
    assert g.detect_lang('bonjour ma belle') == 'fr'
    assert g.detect_lang('oi tudo bem') == 'pt'
    assert g.detect_lang('hallo wie geht es dir') == 'de'
    assert g.detect_lang('i want to die') == 'en'


def test_fallbacks_history_pick_account():
    assert g.detect_lang('😍', 'en', ['আমি তোমাকে']) == 'bn'
    assert g.detect_lang('😍', '', (), 'es') == 'es'
    assert g.detect_lang('😍', 'bn') == 'bn'
    assert g.detect_lang('tumi kemon acho', 'bn') == 'bn'       # Banglish
    assert g.detect_lang('tumi kemon acho', '', (), 'bn') == 'bn'
    assert g.detect_lang('ok', 'en') == 'en'


def test_reply_check_and_directives():
    assert not g.reply_ok('Привет, милый мой', 'es', 'hola')
    assert not g.reply_ok('Hello baby', 'bn', 'আমি')
    assert g.reply_ok('আমি তোমাকে', 'bn', 'আমি')
    assert g.reply_ok('tumi khub mishti', 'bn', 'tumi kemon acho')
    assert 'бенгальском' in g.directive('bn') and 'латиницей' in g.directive('bn')
    assert g.directive('en') == g.DIRECTIVE
    assert g.name_line('ru') == ''


def test_finish_or_drop_keeps_bengali():
    assert finish_or_drop('আমি তোমাকে', True, 'bn') == 'আমি তোমাকে'
    assert finish_or_drop('আমি তোমাকে ভালোবাসি। তুমি কেমন', False, 'bn') == 'আমি তোমাকে ভালোবাসি।'


def test_wiring():
    assert 'lang_guard.remember(db_user_id, _own)' in CHAT
    assert CHAT.count('lang_guard.lang_for_push(db_user_id, language_code)') == 3
    assert "app.router.add_post('/webapp/api/lang', _webapp_api_lang)" in MAIN
    assert "_ru_or_en(request.query.get('lang', 'ru'))" in MAIN


def test_retention_language_codes_and_copy():
    from services import ui_lang

    assert ui_lang.APP_LANGS == frozenset(('ru', 'en', 'es', 'it', 'fr', 'zh', 'ja', 'bn'))
    assert ui_lang.app_lang('es-MX') == 'es'
    assert ui_lang.app_lang('zh-hans') == 'zh'
    assert ui_lang.app_lang('pt-br') == 'en'
    assert ui_lang.app_lang('') == 'ru'
    for lang in ui_lang.APP_LANGS:
        assert ui_lang.flow_text(lang, 'open_chat')
        assert ui_lang.flow_text(lang, 'open_app')
        assert ui_lang.flow_text(lang, 'selfie_caption')
        assert ui_lang.flow_text(lang, 'welcome_edit', amount=25)
        assert ui_lang.flow_text(lang, 'welcome_edit_plain')
    assert HTML.count('chat_hints:') == 8
    assert HTML.count('day1_hints:') == 8
    assert "'&open=1' + '&lang=' + LANG" in HTML


def test_webapp_bengali():
    assert "const APP_LANGS = ['ru', 'en', 'es', 'it', 'fr', 'zh', 'ja', 'bn'];" in HTML
    assert "bn: 'বাংলা'" in HTML
    assert '  bn: {' in HTML and "bn: ['মেয়েরা'" in HTML
    assert "fetch('/webapp/api/lang?init_data=" in HTML
    assert "LANG !== 'en'" not in HTML   # rubles only for the Russian interface
