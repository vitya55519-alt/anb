import asyncio
import os
os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake')


def test_refused_enable_thinking_is_flipped_and_remembered(monkeypatch):
    from services import private_photo_service as pps
    monkeypatch.setattr(pps, 'SPICYAPI_KEY', 'k')
    monkeypatch.setattr(pps, 'SPICYAPI_IMAGE_TIMEOUT', 2)
    pps._spicy_thinking_override.clear()
    sent = []

    async def fake_call(method, path, headers=None, **kw):
        if path == '/jobs/createTask':
            sent.append(dict(kw['json']['input']))
            if len(sent) == 1:
                raise RuntimeError('SpicyAPI error: 40004 This model cannot serve this parameter combination '
                                   'right now (enable_thinking=false: this model does not support it)')
            return {'taskId': 't1'}
        return {'state': 'failed', 'errorMessage': 'x'}

    monkeypatch.setattr(pps, '_spicyapi_call', fake_call)
    asyncio.run(pps._spicyapi_render_once('m/edit', 'p', ['u']))
    assert sent[0]['enable_thinking'] is False and sent[1]['enable_thinking'] is True
    assert pps._spicy_thinking_override['m/edit'] is True
    sent.clear()
    asyncio.run(pps._spicyapi_render_once('m/edit', 'p', ['u']))
    assert sent[0]['enable_thinking'] is True  # remembered, no wasted refusal
    pps._spicy_thinking_override.clear()
