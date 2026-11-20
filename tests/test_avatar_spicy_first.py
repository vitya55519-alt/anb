"""V3.167.28: аватар по картинке рисует Spicy, и картинка доезжает до него.

Владелец 20.11: «пусть фото используется как референс, и рисует спайси а не
гемини, и рисует моих моделей». Движок читает ``image_urls`` как «one to ten
publicly fetchable URLs» — base64-строку он не разбирал, лицо рисовалось по
тексту. Картинка уходит через его же бесплатную загрузку (``spicy://f/…``), тем
же путём, что комната гардероба. Gemini из этой цепочки убрана совсем.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from services import photo_service as ps
from services import private_photo_service as pps
from services import spicy_jobs

REF = Path('synthetic-face.jpg')


@pytest.fixture()
def engines(monkeypatch):
    calls: list[str] = []
    refs: list[list[str]] = []
    state = {'spicy_result': b'SPICY', 'spicy_raises': None, 'upload_result': 'spicy://f/abc',
             'upload_raises': None}

    async def fake_upload(data, content_type):
        calls.append(f'upload:{content_type}:{len(data)}')
        if state['upload_raises'] is not None:
            raise state['upload_raises']
        return state['upload_result']

    async def fake_spicy(model, prompt, image_urls, scene='private', **kw):
        calls.append(f'spicy:{model}:{scene}:{len(image_urls or [])}:breaker={kw.get("breaker")}')
        refs.append(list(image_urls or []))
        if state['spicy_raises'] is not None:
            raise state['spicy_raises']
        return state['spicy_result']

    async def fake_t2i(prompt):
        calls.append('spicy_t2i')
        return b'T2I'

    monkeypatch.setattr(spicy_jobs, 'upload', fake_upload)
    monkeypatch.setattr(pps, '_spicyapi_render', fake_spicy)
    monkeypatch.setattr(pps, 'generate_private_photo_t2i', fake_t2i)
    monkeypatch.setattr(pps, 'spicyapi_last_error', lambda: 'timeout_or_empty')
    monkeypatch.setattr(ps, '_image_b64', lambda path: ('QUJDRA==', 'image/jpeg'))
    monkeypatch.setattr(ps, 'record_provider', lambda *a, **k: calls.append(f'record:{a[0]}:{a[1]}'))
    return calls, refs, state


def test_reference_rides_the_spicy_edit_leg(engines):
    calls, refs, _state = engines
    data, mime = asyncio.run(ps.generate_custom_avatar('PROMPT', REF))
    assert (data, mime) == (b'SPICY', 'image/jpeg')
    assert calls[0] == f'upload:image/jpeg:{len(b"ABCD")}'
    assert calls[1] == f'spicy:{pps.SPICYAPI_IMAGE_MODEL}:avatar_edit:1:breaker=False'
    assert refs[0] == ['spicy://f/abc']


def test_the_edit_leg_is_counted(engines):
    calls, _refs, _state = engines
    asyncio.run(ps.generate_custom_avatar('PROMPT', REF))
    assert 'record:photo/spicyapi_edit:True' in calls


def test_gemini_never_draws_an_avatar(engines):
    """V3.167.28 (владелец 20.11: «вырежи»): молчание Spicy — это отказ, а не
    тихая подмена лица другим движком. Запасной движок удалён из файла."""
    calls, _refs, state = engines
    state['spicy_result'] = None
    with pytest.raises(ps.PhotoGenerationError):
        asyncio.run(ps.generate_custom_avatar('PROMPT', REF))
    assert 'gemini' not in calls
    assert not hasattr(ps, '_gemini_edit')
    assert 'record:photo/spicyapi_edit:False' in calls
    assert 'record:photo/gemini' not in ' '.join(calls)


def test_failure_reason_is_carried_into_the_error(engines):
    _calls, _refs, state = engines
    state['spicy_result'] = None
    with pytest.raises(ps.PhotoGenerationError) as exc:
        asyncio.run(ps.generate_custom_avatar('PROMPT', REF))
    assert 'spicy/timeout_or_empty' in exc.value.reason


def test_spicy_exception_is_reported_not_swallowed(engines):
    _calls, _refs, state = engines
    state['spicy_raises'] = RuntimeError('boom')
    with pytest.raises(ps.PhotoGenerationError) as exc:
        asyncio.run(ps.generate_custom_avatar('PROMPT', REF))
    assert 'spicy/RuntimeError' in exc.value.reason


def test_upload_failure_keeps_the_old_inline_picture(engines):
    """Загрузка карточки не удалась — рисуем хотя бы так, как рисовали раньше."""
    calls, refs, state = engines
    state['upload_raises'] = RuntimeError('upload_slot')
    data, _mime = asyncio.run(ps.generate_custom_avatar('PROMPT', REF))
    assert data == b'SPICY'
    assert refs[0] == ['data:image/jpeg;base64,QUJDRA==']
    assert any(c.startswith('spicy:') for c in calls)


def test_no_reference_stays_text_to_image(engines):
    calls, _refs, _state = engines
    data, mime = asyncio.run(ps.generate_custom_avatar('PROMPT'))
    assert (data, mime) == (b'T2I', 'image/jpeg')
    assert calls == ['spicy_t2i', 'record:photo/spicyapi_t2i:True']
