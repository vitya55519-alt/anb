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
