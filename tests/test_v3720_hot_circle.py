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


def test_render_sends_seedance_input(monkeypatch):
    # V3.73.0: Seedance 2.5 Spicy, silent, frame uploaded as spicy://
    from services import spicy_jobs, spend_service
    calls = []

    async def fake_run(model, block, *, timeout, first_wait=3.0):
        calls.append((model, dict(block)))
        return b'mp4bytes', 'video/mp4', 1.08

    async def fake_upload(data, ctype):
        assert ctype == 'image/jpeg'
        return 'spicy://f/fil_frame'

    monkeypatch.setattr(spicy_jobs, 'run', fake_run)
    monkeypatch.setattr(spicy_jobs, 'upload', fake_upload)
    monkeypatch.setattr(spend_service, 'record_image_spend', lambda *a, **k: None)
    assert asyncio.run(hc.render(b'jpeg', 'ru')) == b'mp4bytes'
    (model, block), = calls
    assert model == 'bytedance/seedance-2.5-spicy/image-to-video'
    assert block['image_url'] == 'spicy://f/fil_frame'
    assert block['generate_audio'] is False and 'audio_url' not in block
    assert block['resolution'] == '480p' and block['duration_seconds'] == 5
    assert 'breasts' in block['prompt'] and 'Adult woman' in block['prompt']


def test_endpoint_gates_and_charges_after_success():
    from config import HOT_CIRCLE_PEACH_COST
    assert HOT_CIRCLE_PEACH_COST == 4000
    block = MAIN[MAIN.index('async def _webapp_api_chat_media('):MAIN.index('async def _webapp_media(')]
    assert "if kind == 'hotcircle':" in block
    assert 'is_custom_character(character_id)' in block
    assert "'error': 'adult_confirm'" in block
    assert 'get_photo_credits(telegram_id) < HOT_CIRCLE_PEACH_COST' in block
    assert 'spend_peaches(telegram_id, HOT_CIRCLE_PEACH_COST)' in block[block.index('def _finish():'):]
    assert "payload['circle_offer'] = offer" in MAIN
    assert 'data-cmedia="hotcircle"' in INDEX
    # V3.73.0: one tap from the «✨ Возможности» sheet
    assert "getElementById('featHotCircle').addEventListener('click', () => requestMedia('hotcircle'))" in INDEX
