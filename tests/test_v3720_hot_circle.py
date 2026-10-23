"""V3.72.0: «🔥 горячий кружок» — paid Wan 2.6 Spicy circle with her TTS
voice, offered (never auto-sent) in flirty moments."""
import asyncio
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")

import pytest  # noqa: E402

from services import hot_circle_service as hc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


class _Store(dict):
    pass


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch):
    monkeypatch.setattr(hc, '_offered', _Store())


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    # V3.72.1: off by default in production; the rules are tested switched on
    monkeypatch.setattr(hc, 'HOT_CIRCLE_ENABLED', True)


def _offer(uid, user, answer, **kw):
    args = dict(is_custom=False, adult_confirmed=True, level=4)
    args.update(kw)
    return hc.offer_for(uid, 'anna_01', user, answer, **args)


def test_flirty_moment_offers_once_a_day():
    assert _offer(1, 'хочу тебя обнять', 'иди ко мне') == {'hot': True}
    assert _offer(1, 'хочу тебя поцеловать', 'ммм') is None


def test_no_offer_in_plain_talk_or_low_level():
    assert _offer(2, 'как прошёл день?', 'нормально, работала') is None
    assert _offer(3, 'хочу тебя поцеловать', 'ммм', level=2) is None


def test_never_hot_for_custom_or_unconfirmed():
    assert _offer(4, 'хочу тебя поцеловать', 'ммм', is_custom=True) is None
    assert _offer(5, 'хочу тебя поцеловать', 'ммм', adult_confirmed=False) is None
    # an explicit ask still shows the regular circle, without the hot one
    assert _offer(6, 'запиши мне кружок', 'ок', is_custom=True) == {'hot': False}


def test_explicit_ask_always_offers():
    assert _offer(7, 'запиши кружочек', 'хорошо') == {'hot': True}
    assert _offer(7, 'а ещё кружок?', 'ладно') == {'hot': True}


def test_render_sends_voice_and_wan_input(monkeypatch):
    from services import spicy_jobs, spend_service
    from services import spicy_video_service
    calls = []

    async def fake_run(model, block, *, timeout, first_wait=3.0):
        calls.append((model, dict(block)))
        if 'tts' in model:
            return b'ID3audio', 'audio/mpeg', 0.001
        return b'mp4bytes', 'video/mp4', 0.475

    async def fake_upload(data, ctype):
        assert ctype == 'audio/mpeg'
        return 'spicy://f/fil_audio'

    monkeypatch.setattr(spicy_jobs, 'run', fake_run)
    monkeypatch.setattr(spicy_jobs, 'upload', fake_upload)
    monkeypatch.setattr(spend_service, 'record_image_spend', lambda *a, **k: None)
    monkeypatch.setattr(spicy_video_service, 'park_frame', lambda b, m='image/jpeg': 'https://x/webapp/vsrc/t')
    out = asyncio.run(hc.render(b'jpeg', 'ru'))
    assert out == b'mp4bytes'
    tts, wan = calls
    assert tts[0] == 'xai/grok-tts/text-to-speech' and tts[1]['voice_id'] == 'eve' and tts[1]['language'] == 'ru'
    assert wan[0] == 'alibaba/wan-2.6-spicy/image-to-video'
    assert wan[1]['audio_url'] == 'spicy://f/fil_audio'
    assert wan[1]['duration_seconds'] == 5 and wan[1]['resolution'] == '720p'
    assert 'underage' in wan[1]['negative_prompt']


def test_endpoint_gates_and_charges_after_success():
    from config import HOT_CIRCLE_PEACH_COST
    assert HOT_CIRCLE_PEACH_COST == 1500
    block = MAIN[MAIN.index('async def _webapp_api_chat_media('):MAIN.index('async def _webapp_media(')]
    assert "if kind == 'hotcircle':" in block
    assert 'is_custom_character(character_id)' in block
    assert "'error': 'adult_confirm'" in block
    assert 'get_photo_credits(telegram_id) < HOT_CIRCLE_PEACH_COST' in block
    assert 'spend_peaches(telegram_id, HOT_CIRCLE_PEACH_COST)' in block[block.index('def _finish():'):]
    assert "payload['circle_offer'] = offer" in MAIN
    assert 'data-cmedia="hotcircle"' in INDEX


def test_off_by_default():
    from config import HOT_CIRCLE_ENABLED
    assert HOT_CIRCLE_ENABLED is False
