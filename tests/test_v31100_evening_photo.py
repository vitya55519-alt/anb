"""V3.110.0: evening photo from user generations + morning voice at 9/20 MSK."""
import asyncio
from pathlib import Path

from services import evening_voice as ev

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_prompt_prefilter_drops_uploads_undress_and_nude():
    assert ev.candidate_prompt_ok('street')
    assert ev.candidate_prompt_ok('Хочу фото в красивом белье')
    # undress passes the text filter only with a plain source file; the source
    # itself is then checked to be a bot render of her in _candidates
    assert ev.candidate_prompt_ok('undress: /webapp/media/1793900350370_61454529.jpg')
    assert ev.undress_source('undress: /webapp/media/17_6.jpg') == '17_6.jpg'
    assert not ev.candidate_prompt_ok('undress: https://evil/x.jpg')
    assert ev.undress_source('undress: /webapp/media/../x.jpg extra') is None
    assert not ev.candidate_prompt_ok('animate: /webapp/media/1_2.jpg')
    assert not ev.candidate_prompt_ok('сделай как тут /webapp/media/abc.jpg')
    assert not ev.candidate_prompt_ok('fully_nude:window:auto:passionate:')
    assert not ev.candidate_prompt_ok('скинь голую')
    assert not ev.candidate_prompt_ok('❌ SpicyAPI: 422\nselfie')
    assert not ev.candidate_prompt_ok('')


def test_qc_parse_and_rules():
    assert ev.parse_qc('{"defect": true, "nudity": "none"}') == {'defect': True, 'nudity': 'none'}
    assert ev.parse_qc('ok') is None
    assert ev.parse_qc('{"defect": "no", "nudity": "none"}') is None
    clean = {'defect': False, 'nudity': 'none'}
    lingerie = {'defect': False, 'nudity': 'lingerie'}
    assert ev.verdict_allows(clean, adult=False)
    assert not ev.verdict_allows(lingerie, adult=False)
    assert ev.verdict_allows(lingerie, adult=True)
    assert not ev.verdict_allows({'defect': False, 'nudity': 'nude'}, adult=True)
    assert not ev.verdict_allows({'defect': True, 'nudity': 'none'}, adult=True)
    assert not ev.verdict_allows({'rejected': True}, adult=True)
    assert not ev.verdict_allows(None, adult=True)


def test_evening_photo_checks_unchecked_and_skips_mutants(monkeypatch):
    monkeypatch.setattr(ev, 'PHOTO_ENABLED', True)
    cands = [(1, 'a.jpg', {'rejected': True}), (2, 'b.jpg', None), (3, 'c.jpg', None)]
    monkeypatch.setattr(ev, '_candidates', lambda c, u: list(cands))
    monkeypatch.setattr(ev, '_media', lambda f: (f.encode(), 'image/jpeg'))
    saved, picks = {}, []
    monkeypatch.setattr(ev, 'save_verdict', lambda g, v: saved.__setitem__(g, v))
    monkeypatch.setattr(ev, '_record_pick', lambda *a: picks.append(a))

    async def qc(data, mime):
        return {'defect': data == b'b.jpg', 'nudity': 'none'}  # b = three arms
    monkeypatch.setattr(ev, 'vision_check', qc)
    import random
    monkeypatch.setattr(random, 'shuffle', lambda x: None)
    got = asyncio.run(ev.evening_photo('anna_01', 5))
    assert got == (b'c.jpg', 'image/jpeg', 'photo')
    assert saved == {2: {'defect': True, 'nudity': 'none'}, 3: {'defect': False, 'nudity': 'none'}}
    assert picks == [(5, 'anna_01', 3, 'c.jpg')]


def test_evening_photo_flag_off(monkeypatch):
    monkeypatch.setattr(ev, 'PHOTO_ENABLED', False)
    assert asyncio.run(ev.evening_photo('anna_01', 5)) is None


def test_scheduler_photo_then_voice_morning_and_evening():
    assert "evening_shot=await _ev.evening_photo(char_id, uid, await asyncio.to_thread(_adult, int(tg_id)))" in SCHED
    assert "morning_voice=await _ev.voice_bytes(text, char_id" in SCHED and "mood='morning'" in SCHED
    block = SCHED[SCHED.index("ritual_voice=evening_voice if kind=='evening' else morning_voice"):SCHED.index("track_event(uid, 'evening_photo_sent'")]
    assert block.index('send_photo') < block.index('send_voice')
    assert 'is_premium' not in block


def test_ritual_hours_9_and_20_moscow():
    import config
    assert (config.RITUAL_MORNING_START_HOUR, config.RITUAL_EVENING_START_HOUR) == (9, 20)
    assert "'Europe/Moscow' if name in ('','UTC','Etc/UTC','GMT') else name" in SCHED


def test_admin_reject_button():
    assert "app.router.add_post('/webapp/api/admin/gen_reject', _webapp_api_admin_gen_reject)" in MAIN
    block = MAIN[MAIN.index('async def _webapp_api_admin_gen_reject'):MAIN.index('async def _webapp_api_admin_generations')]
    assert '_is_admin(telegram_id)' in block and 'reject_generation' in block
    assert '🚫 Брак' in HTML and "'/webapp/api/admin/gen_reject?init_data='" in HTML


def test_undress_source_must_be_her_text_render():
    src = (ROOT / 'services' / 'evening_voice.py').read_text(encoding='utf-8')
    block = src[src.index('def _candidates'):src.index('def _media')]
    assert 'UserGeneration.character_id == character_id' in block
    assert "UserGeneration.kind.in_(('photo', 'hot', 'cosplay'))" in block
    assert "'/webapp/media/' not in (pr or '')" in block
