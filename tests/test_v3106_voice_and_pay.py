"""V3.106.0 — a human voice, free voice taste, Stars first abroad, «без автопродления»."""
from datetime import datetime
from pathlib import Path

from models.app_models import Base, ProductEvent, User
from services import voice_humanize as vh
from services import voice_taste as vt
from services.db import SessionLocal, engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
VOICE = (ROOT / 'services' / 'voice_service.py').read_text(encoding='utf-8')


def test_laughs_sighs_and_soft_lines():
    s = vh.to_speech('ахаха, ну ты даёшь))) я тебя жду 😘', 'anna_01')
    assert s.startswith('[laugh]') and '[giggle]' in s and '😘' not in s and ')' not in s
    s = vh.to_speech('ммм… я так скучаю по тебе 🥺', 'anna_01')
    assert s.startswith('<soft>') and '[breath] ммм' in s and '[sigh]' in s
    assert vh.to_speech('*шепчу на ушко* иди ко мне', 'eva_01') == '<whisper>иди ко мне</whisper>'
    assert vh.to_speech('посмотри https://x.y и @bot', 'eva_01') == 'посмотри и'


def test_at_most_three_tags_and_clean_fallback():
    s = vh.to_speech('хаха))) 😂 😏 🥺 ммм… ну…', 'eva_01')
    assert s.count('[') <= vh.MAX_TAGS
    assert '[' not in vh.strip_tags(s) and '<' not in vh.strip_tags(s)
    assert vh.strip_tags('[laugh], ну ты даёшь [giggle] я жду') == 'ну ты даёшь я жду'


def test_tags_only_for_grok():
    assert 'spoken = voice_humanize.to_speech(text, character_id)' in VOICE
    assert '_tts_grok(spoken or text, character_id)' in VOICE and 'text = plain' in VOICE
    assert MAIN.count('_tts_text(text)') >= 4


def _user():
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        u = User(telegram_id=str(int(datetime.now().timestamp() * 1e6) % 10 ** 12), name='t')
        s.add(u); s.commit()
        return u.id, int(u.telegram_id)


def test_voice_taste_two_free_then_one_offer_a_day():
    uid, tg = _user()
    line = 'привет, я так рада, что ты написал мне сегодня'
    assert vt.decide(tg, line, 1) == ''  # not on his very first message
    assert vt.decide(tg, 'ок', 3) == ''  # too short to be worth a voice
    assert vt.decide(tg, line, 2) == 'voice'
    vt.mark_sent(tg, 'anna_01')
    assert vt.decide(tg, line, 3) == 'voice'
    vt.mark_sent(tg, 'anna_01')
    assert vt.decide(tg, line, 4) == 'offer'
    assert vt.decide(tg, line, 5) == ''  # once a day
    with SessionLocal() as s:
        assert s.query(ProductEvent).filter(ProductEvent.user_id == uid,
                                            ProductEvent.event_name == vt.SENT).count() == 2


def test_wiring_app_and_pay_sheet():
    assert 'voice_taste.decide(telegram_id, text, mine)' in MAIN and "payload['voice_offer'] = True" in MAIN
    assert 'j.voice_offer' in HTML and "quickBuy('voice')" in HTML
    assert "if (LANG !== 'ru') {\n    rows.push(starsRow);" in HTML
    assert 'Apple Pay / Google Pay' in HTML
    assert 'Разовый платёж · без автопродления' in HTML and 'One-time payment · no auto-renewal' in HTML
    assert 'id="payNote"' in HTML
    assert 'разовый платёж, без автопродления' in MAIN


def test_free_limit_tightens_from_day_four():
    from datetime import datetime
    from config import FREE_LATE_FROM_DAY, FREE_MESSAGES_PER_DAY, FREE_MESSAGES_PER_DAY_LATE
    from services.access_service import free_limit_for
    now = datetime(2026, 11, 10, 12, 0)
    assert FREE_LATE_FROM_DAY == 4 and FREE_MESSAGES_PER_DAY_LATE == 10
    assert free_limit_for(None, now) == FREE_MESSAGES_PER_DAY
    assert free_limit_for(datetime(2026, 11, 8, 23, 0), now) == FREE_MESSAGES_PER_DAY  # day 3
    assert free_limit_for(datetime(2026, 11, 7, 0, 5), now) == 10  # day 4
    from services import legal_service
    src = (ROOT / 'services' / 'legal_service.py').read_text(encoding='utf-8') if 'ROOT' in globals() else ''
    assert 'FREE_MESSAGES_PER_DAY_LATE' in (src or open(legal_service.__file__, encoding='utf-8').read())


def test_gemini38_is_first_voice_with_its_own_tags():
    from services import voice_humanize as vh
    t, style = vh.for_gemini(vh.to_speech('ахаха, ну ты даёшь))) я тебя жду 😘'))
    assert '<laugh>' in t and '[' not in t and style == 'vocal_smile'
    t, style = vh.for_gemini(vh.to_speech('*шепчу* иди ко мне…'))
    assert style == 'whisper' and '<whisper>' not in t and '<short pause>' in t
    t, style = vh.for_gemini('<soft>я скучала [sigh] очень</soft>')
    assert t == 'я скучала <sigh> очень' and style == 'empathetic'
    src = open(vh.__file__.replace('voice_humanize', 'voice_service'), encoding='utf-8').read()
    assert src.index('_tts_spicy_gemini(spoken or text') < src.index('_tts_grok(spoken or text')
    assert "'voice_id': gemini_voice_for(character_id)" in src and 'tempo=1.0' in src
    from config import SPICY_GEMINI_TTS_MODEL
    assert SPICY_GEMINI_TTS_MODEL == 'google/gemini-3.8-flash-tts/text-to-speech'


def test_gemini38_request_shape(monkeypatch):
    import asyncio
    from services import spend_service, spicy_jobs
    from services import voice_service as vs
    sent = []

    async def fake_run(model, block, *, timeout, first_wait=3.0):
        sent.append((model, dict(block)))
        return b'RIFFwav', 'audio/wav', 0.0016

    async def fake_opus(wav, tempo=None):
        assert tempo == 1.0
        return b'OggS' + wav

    monkeypatch.setattr(vs, 'SPICY_GEMINI_TTS_ENABLED', True)
    monkeypatch.setattr(vs, 'SPICYAPI_KEY', 'k')
    monkeypatch.setattr(spicy_jobs, 'run', fake_run)
    monkeypatch.setattr(vs, '_convert_wav_to_opus', fake_opus)
    monkeypatch.setattr(spend_service, 'record_image_spend', lambda *a, **k: None)
    out = asyncio.run(vs.synthesize_bytes('ахах, ну ты даёшь))) я тебя жду', character_id='anna_01'))
    assert out == b'OggSRIFFwav'
    model, block = sent[0]
    assert model == 'google/gemini-3.8-flash-tts/text-to-speech'
    assert block['voice_id'] == 'Leda' and '<laugh>' in block['text'] and block['style'] == 'vocal_smile'
    assert 'русская речь' in block['instructions'] and 'playful' in block['instructions']
