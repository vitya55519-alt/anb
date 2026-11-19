"""V3.167.26: аватар с фотопромптом рисует сначала Spicy, Gemini — запасная.

Владелец 19.11: «вместо Гимины рисует Спайси» — конструкторский и студийный
аватар с загруженным лицом идёт сначала через SpicyAPI edit; Gemini вызывается
только когда Spicy молчит или упала. Без референса — как и раньше, Spicy t2i.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from services import photo_service as ps
from services import private_photo_service as pps

REF = Path('synthetic-face.jpg')


@pytest.fixture()
def engines(monkeypatch):
    calls: list[str] = []
    state = {'spicy_result': b'SPICY', 'spicy_raises': None,
             'gemini_result': (b'GEMINI', 'image/png'), 'gemini_raises': None}

    async def fake_spicy(model, prompt, image_urls, scene='private', **kw):
        calls.append(f'spicy:{model}:{scene}:{len(image_urls or [])}')
        if state['spicy_raises'] is not None:
            raise state['spicy_raises']
        return state['spicy_result']

    async def fake_gemini(prompt, reference_path=None):
        calls.append('gemini')
        if state['gemini_raises'] is not None:
            raise state['gemini_raises']
        return state['gemini_result']

    async def fake_t2i(prompt):
        calls.append('spicy_t2i')
        return b'T2I'

    monkeypatch.setattr(pps, '_spicyapi_render', fake_spicy)
    monkeypatch.setattr(pps, 'generate_private_photo_t2i', fake_t2i)
    monkeypatch.setattr(pps, 'spicyapi_last_error', lambda: 'timeout_or_empty')
    monkeypatch.setattr(ps, '_gemini_edit', fake_gemini)
    monkeypatch.setattr(ps, '_file_data_uri', lambda path: 'data:image/jpeg;base64,AAA')
    monkeypatch.setattr(ps, 'gemini_on_cooldown', lambda: False)
    monkeypatch.setattr(ps, 'record_provider', lambda *a, **k: None)
    return calls, state


def test_reference_prefers_spicy_edit(engines):
    calls, _state = engines
    data, mime = asyncio.run(ps.generate_custom_avatar('PROMPT', REF))
    assert (data, mime) == (b'SPICY', 'image/jpeg')
    assert calls == [f'spicy:{pps.SPICYAPI_IMAGE_MODEL}:avatar_edit:1']


def test_reference_falls_back_to_gemini_when_spicy_empty(engines):
    calls, state = engines
    state['spicy_result'] = None
    data, mime = asyncio.run(ps.generate_custom_avatar('PROMPT', REF))
    assert data == b'GEMINI'
    assert calls[-1] == 'gemini'


def test_reference_falls_back_when_spicy_raises(engines):
    calls, state = engines
    state['spicy_raises'] = RuntimeError('boom')
    data, _mime = asyncio.run(ps.generate_custom_avatar('PROMPT', REF))
    assert data == b'GEMINI'
    assert calls[-1] == 'gemini'


def test_reference_reports_whole_chain_when_both_fail(engines):
    _calls, state = engines
    state['spicy_result'] = None
    state['gemini_raises'] = ps.PhotoGenerationError('gemini_image', 'http_429')
    with pytest.raises(ps.PhotoGenerationError) as exc:
        asyncio.run(ps.generate_custom_avatar('PROMPT', REF))
    assert 'spicy/timeout_or_empty' in exc.value.reason
    assert 'gemini/' in exc.value.reason


def test_no_reference_stays_text_to_image(engines):
    calls, _state = engines
    data, mime = asyncio.run(ps.generate_custom_avatar('PROMPT'))
    assert (data, mime) == (b'T2I', 'image/jpeg')
    assert calls == ['spicy_t2i']
