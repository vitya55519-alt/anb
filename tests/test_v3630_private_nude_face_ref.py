"""V3.62.5: nude «Наедине» shots edit from her face reference instead of a
reference-free text-to-image that drew a different woman."""
import asyncio
import io

from PIL import Image

import services.private_photo_service as pps
from services.private_photo_service import PrivatePhotoRequest, PRIVATE_PHOTO_CATEGORIES

buf = io.BytesIO(); Image.new('RGB', (8, 8), 'red').save(buf, 'JPEG'); JPG = buf.getvalue()


def _req(cat):
    t = PRIVATE_PHOTO_CATEGORIES[cat]['types'][0]['id']
    return PrivatePhotoRequest(category=cat, type_id=t, location_id='bedroom', mood_id='sensual', character_id='vika_01')


def test_nude_prompt_has_face_lock_and_reference_note():
    p = pps.build_private_photo_prompt(_req('fully_nude'), '', use_reference=True)
    assert 'FACE LOCK:' in p and 'REFERENCE IMAGE 1 gives ONLY her face' in p
    assert 'Location: Bedroom' in p


def test_pool_cutoff_not_older_than_switch():
    assert pps.PRIVATE_POOL_SINCE >= '2026-10-15T20:00:00'


def test_hot_nude_uses_face_reference_edit(monkeypatch):
    import main
    calls = []

    async def fake(model, prompt, urls, scene='x', **k):
        calls.append((model, urls))
        return JPG

    monkeypatch.setattr(pps, '_spicyapi_render', fake)
    monkeypatch.setattr(main, 'consume_free_private_photo', lambda *a: True, raising=False)
    import services.private_photo_service as svc
    monkeypatch.setattr(svc, 'consume_free_private_photo', lambda *a: True)
    monkeypatch.setattr(svc, 'cache_get', lambda *a: None)
    monkeypatch.setattr(svc, 'pool_get', lambda *a: None)
    tid = 5550077
    main.ensure_user(tid)
    data, _mime, _ext = asyncio.run(main._webapp_media_hot(tid, 'vika_01', 'fully_nude'))
    assert data == JPG
    assert calls[0][0] == pps.SPICYAPI_IMAGE_MODEL
    assert calls[0][1] == [f'{pps.PUBLIC_BASE_URL}/webapp/photo/vika_01?i=0']
