"""V3.107.0 — «Без сюрпризов»: honest one-time card + crypto row via Platega."""
from pathlib import Path

from services import honest_card

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_facts_come_from_live_config():
    import config
    f = honest_card.facts()
    assert f['free_messages'] == config.FREE_MESSAGES_PER_DAY
    assert f['free_messages_later'] <= f['free_messages']
    assert f['free_photos'] == config.CHAT_FREE_PHOTOS_PER_DAY
    assert f['week_stars'] == config.PREMIUM_WEEKLY_STARS
    assert f['support'] == config.SUPPORT_BOT_USERNAME
    assert set(f) >= {'enabled', 'free_voice', 'week_rub', 'later_from_day'}


def test_no_fake_social_proof_on_the_card():
    src = (ROOT / 'services' / 'honest_card.py').read_text(encoding='utf-8')
    for bad in ('купили', 'покупают', 'users bought', 'из 5'):
        assert bad not in src
    block = HTML[HTML.index('function openHonest'):HTML.index('async function loadMe')]
    assert 'из 5' not in block and 'count' not in block


def test_me_payload_and_sheet_wiring():
    assert "me['honest'] = honest_card.facts()" in MAIN
    assert 'id="honestmodal"' in HTML and 'id="honestClose"' in HTML
    assert 'anbHonestSeen' not in HTML and '_honestShown = true;' in HTML
    assert 'maybeShowHonest();' in HTML and 'id="honestReopen"' in HTML
    assert "hn_title: 'Честно о нас 💜'" in HTML and "hn_title: 'Honestly about us 💜'" in HTML
    assert "hn_go: 'Ок, выбрать героиню'" in HTML and 'без автопродления' in HTML
    # owner: stars abroad, rubles at home
    assert "(LANG === 'ru' && f.week_rub) ? f.week_rub + ' ₽' : f.week_stars + ' ⭐'" in HTML


def test_crypto_row_goes_to_platega_page():
    assert "if method == 'sbp' or method == 'platega_crypto':" in MAIN
    assert 'data-m="platega_crypto"' in HTML
    assert "pay_crypto_pg: 'Криптовалюта'" in HTML


# ── evening voice ─────────────────────────────────────────────────────────
import asyncio

from services import evening_voice as ev

SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')


def test_evening_voice_language_guard():
    assert ev.language_matches('как прошёл твой день?', 'ru')
    assert not ev.language_matches('как прошёл твой день?', 'en')
    assert ev.language_matches(ev.en_evening_line(), 'en')
    assert ev.spoken_text('привет 😘 *шепчу*  ты где?') == 'привет шепчу ты где?'
    assert len(ev.caption('а' * 1500)) == ev.CAPTION_LIMIT


def test_evening_voice_skips_wrong_language(monkeypatch):
    called = []

    async def fake(text, voice=None, character_id=None, mood=None):
        called.append(text)
        return b'ogg'

    import services.voice_service as vs
    monkeypatch.setattr(vs, 'synthesize_bytes', fake)
    assert asyncio.run(ev.voice_bytes('как прошёл день? 🌙', 'anna_01', 'en')) is None
    assert asyncio.run(ev.voice_bytes('как прошёл день? 🌙', 'anna_01', 'ru')) == b'ogg'
    assert called == ['как прошёл день?']


def test_scheduler_sends_evening_as_voice_for_everyone():
    assert "evening_voice=await _ev.voice_bytes(text, char_id, _el)" in SCHED
    assert "await bot.send_voice(int(tg_id), BufferedInputFile(ritual_voice" in SCHED
    assert "track_event(uid, f'{kind}_voice_sent'" in SCHED
    assert "text=_ev.en_evening_line()" in SCHED
    # no Premium gate on the evening voice
    block = SCHED[SCHED.index('evening_voice=None'):SCHED.index("track_event(uid, f'{kind}_voice_sent'")]
    assert 'is_premium' not in block


# ── wishes from the card → support chat ───────────────────────────────────
from services import app_feedback as fb


def test_feedback_rate_limit_and_clean():
    fb._sent.clear()
    assert fb.clean('  хочу   больше\nдевушек ') == 'хочу больше девушек'
    assert len(fb.clean('x' * 5000)) == fb.MAX_LEN
    for i in range(fb.PER_HOUR):
        assert fb.allowed(1, now=1000 + i)
        fb.remember(1, now=1000 + i)
    assert not fb.allowed(1, now=1100)
    assert fb.allowed(1, now=1000 + 3700)


def test_feedback_card_title_and_reply_routing():
    from services import support_desk
    card = fb.admin_card(424242, 'Петя', 'petya', 'добавьте аниме')
    assert card.startswith('💡 Предложение из приложения') and 'добавьте аниме' in card
    assert support_desk.user_id_from_card(card) == 424242


def test_feedback_endpoint_and_ui():
    assert "app.router.add_post('/webapp/api/feedback', _webapp_api_feedback)" in MAIN
    assert 'sender = _SUPPORT_BOT or bot' in MAIN and '_SUPPORT_BOT = support_bot' in MAIN
    assert 'id="fbText"' in HTML and "'/webapp/api/feedback?init_data='" in HTML
    assert "fb_title: 'Будем рады вашим пожеланиям 💡'" in HTML


def test_support_answer_falls_back_to_main_bot():
    block = MAIN[MAIN.index('async def _send_answer('):MAIN.index('async def _support_appeal(')]
    assert 'await bot.send_message(user_id, desk.ANSWER_PREFIX + body)' in block


# ── V3.108.0: soft evening mood + /voicecast ──────────────────────────────
VOICE = (ROOT / 'services' / 'voice_service.py').read_text(encoding='utf-8')


def test_evening_mood_reaches_gemini_tts():
    import services.voice_service as vs
    assert 'тихо, мягко и медленно' in vs._SPICY_GEMINI_MOOD['evening']['ru']
    assert "_tts_spicy_gemini(spoken or text, character_id, mood=mood)" in VOICE
    assert "mood: str = 'evening'" in (ROOT / 'services' / 'evening_voice.py').read_text(encoding='utf-8')


def test_voicecast_is_admin_only_and_needs_confirm():
    block = MAIN[MAIN.index("async def _voice_cast_audio("):MAIN.index("@dp.message(Command('stats', 'adminstats'))")]
    assert block.count('not in ADMIN_TELEGRAM_IDS') == 2
    assert "callback_data='vcast:go'" in block and '_voice_cast_running' in block
    # owner: exactly two recordings (ru + en), reused for everyone
    assert 'key = lang' in block and 'audio = await _voice_cast_audio(cache, cast_char, lang)' in block
    assert set(ev.CAST_LINES) == {'ru', 'en'} and ev.language_matches(ev.CAST_LINES['en'], 'en')



def test_voicecast_sends_both_versions_to_admin():
    block = MAIN[MAIN.index("@dp.message(Command('voicecast'))"):MAIN.index("@dp.callback_query(F.data == 'vcast:go')")]
    assert "for _lang in ('ru', 'en'):" in block and 'voice_{_lang}.ogg' in block
