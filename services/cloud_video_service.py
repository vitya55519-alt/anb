"""Public-cloud image-to-video providers with stable APIs.

Unlike the best-effort Hugging Face Gradio spaces, these services expose
documented REST APIs with proper rate limiting and a free tier. They are
used as the second/third lines of defence in the video job after
Gemini/Veo fails and before the flaky HF-space walk.

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


class CloudVideoError(RuntimeError):
    pass


def replicate_available() -> bool:
    return bool(REPLICATE_API_TOKEN)


def fal_available() -> bool:
    return bool(FAL_KEY)


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
    """Image-to-video via Replicate (minimax/video-01 by default).

    Lazy-imports the SDK so that missing the package does not break boot.
    """
    if not replicate_available():
        raise CloudVideoError('replicate_not_configured')
    if not image_bytes:
        raise CloudVideoError('empty_image')

    import replicate
    from replicate.exceptions import ReplicateError

    prompt = prompt or ANIMATION_PROMPT
    tmp_path = await _save_bytes(image_bytes, mime_type)
    try:
        input_payload = {
            "first_frame_image": Path(tmp_path),
            "prompt": prompt,
        }
        run = await asyncio.to_thread(
            replicate.run,
            REPLICATE_VIDEO_MODEL,
            input=input_payload,
            wait=REPLICATE_VIDEO_TIMEOUT_SECONDS,
        )
    except ReplicateError as exc:
        logger.warning('Replicate video error model=%s error=%s', REPLICATE_VIDEO_MODEL, exc)
        raise CloudVideoError(f'replicate:{exc}') from exc
    except Exception as exc:
        logger.warning('Replicate video unexpected error: %s', exc)
        raise CloudVideoError(f'replicate_call_failed:{type(exc).__name__}') from exc
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
