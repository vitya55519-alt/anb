"""V3.69.0: every video and circle goes through SpicyAPI.

Owner (2026-10-21): «замкнуть фотки и видео на этот сайт» — Gemini/Veo,
Replicate, fal and the HF spaces are out of the video chains; one provider,
one bill. SpicyAPI image-to-video (MiniMax H3) renders the voice together with
the picture, so the circle phrase is actually spoken.

SpicyAPI fetches the start frame by URL, so the frame is parked for a short
time in memory behind an unguessable token (``/webapp/vsrc/<token>``).

Safety line (same as photos, V3.64.6 / PR #76): a frame the user uploaded may
show a real person, so it never goes through the uncensored model —
``safe=True`` picks the regular H3 model and pins a fully clothed,
non-sexual prompt. The studio (user's own frame or prompt) always runs safe;
uploads stay admin-only on top of that.
"""
from __future__ import annotations

import asyncio
import io
import logging
import secrets
import time
import uuid

import aiohttp

from config import (
    PUBLIC_BASE_URL,
    SPICYAPI_KEY,
    SPICYAPI_VIDEO_MODEL,
    SPICYAPI_VIDEO_SAFE_MODEL,
    SPICYAPI_VIDEO_RESOLUTION,
    SPICYAPI_VIDEO_SECONDS,
    SPICYAPI_VIDEO_TIMEOUT,
    SPICYAPI_VIDEO_COST_PER_SECOND_USD,
)
from services.cloud_video_service import ANIMATION_PROMPT, CloudVideoError

logger = logging.getLogger(__name__)

SAFE_UPLOAD_PROMPT = (
    'She stays fully clothed in the exact outfit from the photo the whole time. '
    'Non-sexual, no undressing, no nudity, no suggestive motion.'
)

# token -> (bytes, mime, expires_at). One process serves the web app and the
# bot, so an in-memory shelf is enough; SpicyAPI fetches the frame within
# seconds of createTask.
_FRAMES: dict[str, tuple[bytes, str, float]] = {}
_FRAME_TTL = 30 * 60


def spicy_video_available() -> bool:
    return bool(SPICYAPI_KEY and PUBLIC_BASE_URL)


def _gc() -> None:
    now = time.time()
    for k in [k for k, (_, _, exp) in _FRAMES.items() if exp < now]:
        _FRAMES.pop(k, None)


def park_frame(image_bytes: bytes, mime_type: str = 'image/jpeg') -> str:
    """Park a start frame and return its public URL."""
    _gc()
    token = secrets.token_urlsafe(24)
    _FRAMES[token] = (image_bytes, mime_type or 'image/jpeg', time.time() + _FRAME_TTL)
    return f'{PUBLIC_BASE_URL}/webapp/vsrc/{token}'


def parked_frame(token: str) -> tuple[bytes, str] | None:
    item = _FRAMES.get(token or '')
    if not item or item[2] < time.time():
        return None
    return item[0], item[1]


def square_frame(image_bytes: bytes) -> bytes:
    """Crop to 1:1 for a Telegram video note (the model keeps the frame's
    aspect). The crop leans to the top, where the face is in a selfie."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        w, h = im.size
        side = min(w, h)
        left = (w - side) // 2
        top = min(int(h * 0.08), h - side) if h > w else 0
        im = im.crop((left, top, left + side, top + side))
        if side > 1024:
            im = im.resize((1024, 1024))
        out = io.BytesIO()
        im.save(out, format='JPEG', quality=92)
        return out.getvalue()
    except Exception:
        logger.warning('square_frame failed, sending the frame as is', exc_info=True)
        return image_bytes


async def animate_image_spicy(
    image_bytes: bytes,
    mime_type: str = 'image/jpeg',
    prompt: str | None = None,
    *,
    safe: bool = False,
    seconds: int | None = None,
    scene: str = 'video',
) -> bytes:
    """Image-to-video via SpicyAPI. Raises CloudVideoError on any failure
    (same contract as the old engines, so callers keep their refund paths)."""
    if not spicy_video_available():
        raise CloudVideoError('spicyapi_video_not_configured')
    if not image_bytes:
        raise CloudVideoError('empty_image')
    from services.private_photo_service import _spicyapi_call
    from services import spend_service

    prompt = prompt or ANIMATION_PROMPT
    model = SPICYAPI_VIDEO_MODEL
    if safe:
        model = SPICYAPI_VIDEO_SAFE_MODEL
        prompt = f'{prompt} {SAFE_UPLOAD_PROMPT}'
    seconds = max(3, min(15, int(seconds or SPICYAPI_VIDEO_SECONDS)))
    frame_url = park_frame(image_bytes, mime_type)
    input_block = {
        'image_url': frame_url,
        'prompt': prompt[:1900],
        'duration_seconds': seconds,
        'resolution': SPICYAPI_VIDEO_RESOLUTION,
    }
    try:
        task = await _spicyapi_call(
            'POST', '/jobs/createTask',
            headers={'Idempotency-Key': str(uuid.uuid4())},
            json={'model': model, 'input': input_block},
        )
    except Exception as exc:
        raise CloudVideoError(f'spicyapi_create: {str(exc)[:200]}') from exc
    task_id = task.get('taskId')
    if not task_id:
        raise CloudVideoError('spicyapi_no_task_id')
    logger.info('SpicyAPI video task %s model=%s %ss %s', task_id, model, seconds, SPICYAPI_VIDEO_RESOLUTION)
    video: bytes | None = None
    state = 'queued'
    error = ''
    loop = asyncio.get_event_loop()
    deadline = loop.time() + SPICYAPI_VIDEO_TIMEOUT
    wait = 3.0
    try:
        while loop.time() < deadline:
            await asyncio.sleep(wait)
            wait = min(wait * 1.2, 6.0)
            try:
                info = await _spicyapi_call('GET', f'/jobs/recordInfo?taskId={task_id}')
            except Exception as exc:
                logger.warning('SpicyAPI video poll failed %s: %s', task_id, exc)
                continue
            state = info.get('state')
            if state == 'succeeded':
                assets = (info.get('output') or {}).get('assets') or []
                url = next((a.get('url') for a in assets if a.get('url')), None)
                if url:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
                        async with s.get(url) as resp:
                            if resp.status == 200:
                                video = await resp.read()
                break
            if state in ('failed', 'expired', 'canceled'):
                error = f"{state}: {info.get('errorCode') or info.get('errorMessage')}"
                break
    finally:
        # billed on accept, whatever comes back
        spend_service.record_image_spend(
            'spicyapi_video', scene, SPICYAPI_VIDEO_COST_PER_SECOND_USD * seconds,
            billed=True, success=bool(video),
        )
    if not video:
        raise CloudVideoError(f'spicyapi_video_{error or "timeout_" + str(state)}'[:200])
    return video


def video_engines() -> list:
    """The one engine left, in the (name, fn) shape the callers loop over."""
    return [('spicy', animate_image_spicy)] if spicy_video_available() else []
