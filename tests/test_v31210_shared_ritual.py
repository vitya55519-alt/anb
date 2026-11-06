"""V3.121.0: one ritual (line + voice + photo) per girl, language and day."""
import asyncio
from pathlib import Path

SCHED = Path('services/scheduler_service.py').read_text(encoding='utf-8')


def test_shared_mode_is_default_and_skips_per_user_work():
    assert "RITUAL_SHARED=_os.getenv('RITUAL_SHARED','true')" in SCHED
    i = SCHED.index('if RITUAL_SHARED:')
    j = SCHED.index('else:', i)
    assert '_shared_ritual(kind, msk_day, char_id, _el)' in SCHED[i:j]
    assert 'morning_callback' not in SCHED[i:j]


def test_bundle_built_once_per_girl_language_day(monkeypatch):
    from services import scheduler_service as S, evening_voice as ev
    calls = {'tts': 0, 'photo': 0}

    async def fake_voice(text, char_id, lang, mood='evening'):
        calls['tts'] += 1
        return b'ogg'

    async def fake_photo(char_id, uid, adult=False):
        calls['photo'] += 1
        assert uid is None and adult is False
        return (b'jpg', 'image/jpeg', 'photo')

    monkeypatch.setattr(ev, 'voice_bytes', fake_voice)
    monkeypatch.setattr(ev, 'evening_photo', fake_photo)
    S._shared_bundles.clear()

    async def run():
        a = await S._shared_ritual('evening', '2026-11-06', 'anna_01', 'ru')
        b = await S._shared_ritual('evening', '2026-11-06', 'anna_01', 'ru')
        c = await S._shared_ritual('evening', '2026-11-06', 'anna_01', 'en')
        return a, b, c

    a, b, c = asyncio.run(run())
    assert a is b and a[1] == b'ogg' and a[2][2] == 'photo'
    assert c[0] in ev.EN_EVENING
    assert calls == {'tts': 2, 'photo': 2}
    asyncio.run(S._shared_ritual('morning', '2026-11-07', 'anna_01', 'en'))
    assert all(k[1] == '2026-11-07' for k in S._shared_bundles)
