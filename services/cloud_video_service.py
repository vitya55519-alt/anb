"""Public-cloud image-to-video providers with stable APIs.

V3.19.4: Replicate is the primary video engine (Gemini/Veo was removed).
The remaining chain in main.py is Replicate -> fal.ai -> HF spaces.

Unlike the best-effort Hugging Face Gradio spaces, these services expose
documented REST APIs with proper rate limiting and a free tier. They keep
the video feature alive when one engine fails.

Each ``animate_image_*`` coroutine takes the same inputs and returns the
raw MP4/WebM bytes on success. Failures raise a ``CloudVideoError`` so the
orchestrator can move on to the next engine.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import tempfile
from pathlib import Path

import httpx

from config import (
    REPLICATE_API_TOKEN,
    REPLICATE_VIDEO_MODEL,
    REPLICATE_VIDEO_TIMEOUT_SECONDS,
    FAL_KEY,
    FAL_VIDEO_ENDPOINT,
    FAL_VIDEO_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


ANIMATION_PROMPT = (
    "Animate this exact photo of the same adult woman. Preserve her identity, "
    "face, hair, body proportions, clothing and scene. Natural subtle smile, "
    "one or two blinks, gentle breathing, tiny head movement and realistic "
    "handheld camera micro-motion. No wardrobe change, no body transformation, "
    "no extra people, no sexual action, no nudity, no text or logos. "
    "Photorealistic and calm."
)

SENSUAL_ANIMATION_PROMPT = (
    "Animate this exact photo of the same adult woman. Preserve her identity, "
    "face, hair, body proportions and scene. Slow sensual movement: she runs "
    "her hand through her hair, tilts her head, lets her hand trail along her "
    "waist and hip, a soft teasing smile. Gentle breathing, one or two blinks, "
    "realistic handheld camera micro-motion. No wardrobe change, no body "
    "transformation, no extra people. Photorealistic and intimate."
)

# V3.19.0: user-selectable motion presets, WildGrl-style. Values are
# (button label, animation prompt). 'auto' is not listed: it reuses the
# scene-aware default (SENSUAL_ANIMATION_PROMPT for intimate scenes).
VIDEO_PRESETS: dict[str, tuple[str, str]] = {
    'kiss': ('\U0001f48b Поцелуй', (
        "Animate this exact photo of the same adult woman. Preserve her identity, "
        "face, hair, body and scene. The camera is the viewer's eyes: she slowly "
        "leans in close to the camera, softly purses her lips and presses a gentle "
        "kiss toward the viewer, as if kissing the person holding the camera, then "
        "smiles warmly. Natural breathing, one or two blinks, realistic handheld "
        "camera micro-motion. No wardrobe change, no extra people. Photorealistic."
    )),
    'hug': ('\U0001f917 Обнимашки', (
        "Animate this exact photo of the same adult woman. Preserve her identity, "
        "face, hair, body and scene. The camera is the viewer's eyes: she steps "
        "close and wraps her arms around the viewer in a warm embrace, leaning her "
        "head toward the camera, closing her eyes for a moment and smiling softly "
        "as if hugging someone dear. Warm tender mood, natural breathing, one or "
        "two blinks, realistic handheld camera micro-motion. No wardrobe change, "
        "no extra people. Photorealistic."
    )),
    'dance': ('\U0001f483 Танец', (
        "Animate this exact photo of the same adult woman. Preserve her identity, "
        "face, hair, body and scene. She starts a slow sensual dance to unheard "
        "music: rhythmic sway of hips and shoulders, playful hand movements, a "
        "confident teasing smile. Natural body physics, one or two blinks, "
        "realistic handheld camera micro-motion. No wardrobe change, no extra "
        "people. Photorealistic."
    )),
}


class CloudVideoError(RuntimeError):
    pass


def replicate_available() -> bool:
    return bool(REPLICATE_API_TOKEN)


def fal_available() -> bool:
    return bool(FAL_KEY)


def _replicate_image_param(model: str) -> str:
    """V3.19.4: different Replicate i2v models name the input image key
    differently; map by owner so the default payload works model-agnostic."""
    name = (model or '').lower()
    if name.startswith('minimax'):
        return 'first_frame_image'
    if 'wan' in name:
        return 'img'
    return 'image'


def _suffix_for_bytes(image_bytes: bytes, mime_type: str) -> str:
    if 'png' in (mime_type or ''):
        return '.png'
    # Cheap magic sniff — only needed so we do not misname the file.
    if image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    return '.jpg'


async def _download_video(url: str, *, provider: str) -> bytes:
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        response = await client.get(url)
    if response.status_code >= 400 or not response.content:
        raise CloudVideoError(f'{provider}_download_failed:{response.status_code}')
    return response.content


async def _save_bytes(image_bytes: bytes, mime_type: str) -> str:
    suffix = _suffix_for_bytes(image_bytes, mime_type)
    fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix='annabot_cloud_video_')
    with open(fd, 'wb') as tmp:
        tmp.write(image_bytes)
    return tmp_path


def _extract_video_url(result) -> str | None:
    """Pull a URL out of whichever shape the SDK wraps the response in."""
    stack: list = [result]
    while stack:
        item = stack.pop()
        if item is None:
            continue
        if isinstance(item, str) and item.strip():
            value = item.strip()
            if value.startswith(('http://', 'https://')):
                return value
            if Path(value).exists():
                return value
            continue
        if isinstance(item, dict):
            for key in ('url', 'video', 'video_url', 'src', 'href'):
                if item.get(key):
                    stack.append(item[key])
            continue
        if isinstance(item, (list, tuple)):
            stack.extend(item)
            continue
        # FileOutput-like object from Replicate — try common attributes.
        for attr in ('url', 'video_url', 'value', 'path'):
            candidate = getattr(item, attr, None)
            if candidate:
                stack.append(candidate)
    return None


async def animate_image_replicate(
    image_bytes: bytes,
    mime_type: str = 'image/jpeg',
    prompt: str | None = None,
) -> bytes:
    """Image-to-video via Replicate (minimax/hailuo-2.3-fast by default).

    Lazy-imports the SDK so that missing the package does not break boot.
    """
    if not replicate_available():
        raise CloudVideoError('replicate_not_configured')
    if not image_bytes:
        raise CloudVideoError('empty_image')

    import replicate

    prompt = prompt or ANIMATION_PROMPT
    tmp_path = await _save_bytes(image_bytes, mime_type)
    try:
        client = replicate.Client(api_token=REPLICATE_API_TOKEN)
        input_payload = {
            _replicate_image_param(REPLICATE_VIDEO_MODEL): Path(tmp_path),
            "prompt": prompt,
        }
        # Explicit create + poll instead of the run(wait=...) helper: the API
        # caps the Prefer-wait window at 60s, so run(wait=600) returned an
        # unfinished prediction with no output and the video was lost.
        prediction = await asyncio.to_thread(
            client.predictions.create,
            model=REPLICATE_VIDEO_MODEL,
            input=input_payload,
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + REPLICATE_VIDEO_TIMEOUT_SECONDS
        while prediction.status not in ('succeeded', 'failed', 'canceled'):
            if loop.time() >= deadline:
                raise CloudVideoError(f'replicate_timeout:{prediction.status}')
            await asyncio.sleep(5)
            await asyncio.to_thread(prediction.reload)
        if prediction.status != 'succeeded':
            error_detail = str(getattr(prediction, 'error', '') or '')[:200]
            raise CloudVideoError(f'replicate_{prediction.status}:{error_detail}')
        run = prediction.output
    except CloudVideoError:
        raise
    except Exception as exc:
        logger.warning('Replicate video error model=%s error=%s', REPLICATE_VIDEO_MODEL, exc)
        raise CloudVideoError(f'replicate:{type(exc).__name__}:{str(exc)[:200]}') from exc
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass

    # The run result can be a URL string, a FileOutput, a dict, or a list of those.
    url = _extract_video_url(run)
    if not url:
        logger.warning('Replicate returned no video url result=%s', str(run)[:400])
        raise CloudVideoError('replicate_no_video_url')

    if Path(url).exists():
        data = Path(url).read_bytes()
        if not data:
            raise CloudVideoError('replicate_empty_video')
        return data
    return await _download_video(url, provider='replicate')


async def animate_image_fal(
    image_bytes: bytes,
    mime_type: str = 'image/jpeg',
    prompt: str | None = None,
) -> bytes:
    """Image-to-video via fal.ai (fal-ai/wan2.2/image-to-video by default)."""
    if not fal_available():
        raise CloudVideoError('fal_not_configured')
    if not image_bytes:
        raise CloudVideoError('empty_image')

    import fal_client

    prompt = prompt or ANIMATION_PROMPT
    suffix = _suffix_for_bytes(image_bytes, mime_type)
    mime = mimetypes.guess_type(f'x{suffix}')[0] or ('image/png' if suffix == '.png' else 'image/jpeg')
    b64 = base64.b64encode(image_bytes).decode('ascii')
    data_url = f'data:{mime};base64,{b64}'

    try:
        result = await asyncio.to_thread(
            fal_client.subscribe,
            FAL_VIDEO_ENDPOINT,
            arguments={
                "image_url": data_url,
                "prompt": prompt,
            },
            with_logs=False,
        )
    except Exception as exc:
        logger.warning('fal.ai video error: %s', exc)
        raise CloudVideoError(f'fal_call_failed:{type(exc).__name__}:{str(exc)[:120]}') from exc

    if not isinstance(result, dict):
        raise CloudVideoError('fal_unexpected_response')
    video = result.get('video') or {}
    url = None
    if isinstance(video, dict):
        url = video.get('url')
    elif isinstance(video, str):
        url = video
    if not url:
        # Some fal endpoints return the video under a different key.
        url = result.get('video_url')
    if not url:
        logger.warning('fal.ai returned no video url result=%s', str(result)[:400])
        raise CloudVideoError('fal_no_video_url')

    return await _download_video(url, provider='fal')
