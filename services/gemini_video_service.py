from __future__ import annotations

import asyncio
import base64
import logging
import time

import httpx

from config import (
    GEMINI_API_KEY, GEMINI_VIDEO_ENABLED, GEMINI_VIDEO_MODEL, GEMINI_VIDEO_BASE_URL,
    GEMINI_VIDEO_DURATION_SECONDS, GEMINI_VIDEO_RESOLUTION, GEMINI_VIDEO_ASPECT_RATIO,
    GEMINI_VIDEO_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


class GeminiVideoError(RuntimeError):
    pass


def video_available() -> bool:
    return bool(GEMINI_VIDEO_ENABLED and GEMINI_API_KEY)


async def animate_image(image_bytes: bytes, mime_type: str = 'image/jpeg', prompt: str | None = None) -> bytes:
    if not video_available():
        raise GeminiVideoError('video_disabled')
    if not image_bytes:
        raise GeminiVideoError('empty_image')

    prompt = prompt or (
        'Animate this exact photo of the same adult woman. Preserve her identity, face, hair, body proportions, '
        'clothing and scene. Natural subtle smile, one or two blinks, gentle breathing, tiny head movement and '
        'realistic handheld camera micro-motion. No wardrobe change, no body transformation, no extra people, '
        'no sexual action, no nudity, no text or logos. Photorealistic and calm.'
    )
    payload = {
        'instances': [{
            'prompt': prompt,
            'image': {
                'inlineData': {
                    'mimeType': mime_type,
                    'data': base64.b64encode(image_bytes).decode('ascii'),
                }
            },
        }],
        'parameters': {
            'aspectRatio': GEMINI_VIDEO_ASPECT_RATIO,
            'durationSeconds': str(GEMINI_VIDEO_DURATION_SECONDS),
            'resolution': GEMINI_VIDEO_RESOLUTION,
            'personGeneration': 'allow_adult',
        },
    }
    headers = {'x-goog-api-key': GEMINI_API_KEY, 'Content-Type': 'application/json'}
    timeout = httpx.Timeout(45.0, connect=20.0, read=45.0, write=45.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        start_url = f'{GEMINI_VIDEO_BASE_URL}/models/{GEMINI_VIDEO_MODEL}:predictLongRunning'
        r = await client.post(start_url, headers=headers, json=payload)
        if r.status_code >= 400:
            logger.warning('Gemini video start failed status=%s body=%s', r.status_code, r.text[:800])
            raise GeminiVideoError(f'start_http_{r.status_code}')
        data = r.json()
        operation = data.get('name')
        if not operation:
            raise GeminiVideoError('missing_operation')

        deadline = time.monotonic() + GEMINI_VIDEO_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(10)
            sr = await client.get(f'{GEMINI_VIDEO_BASE_URL}/{operation}', headers={'x-goog-api-key': GEMINI_API_KEY})
            if sr.status_code >= 400:
                raise GeminiVideoError(f'poll_http_{sr.status_code}')
            status = sr.json()
            if not status.get('done'):
                continue
            if status.get('error'):
                logger.warning('Gemini video operation failed error=%s', status.get('error'))
                raise GeminiVideoError('operation_failed')
            try:
                uri = status['response']['generateVideoResponse']['generatedSamples'][0]['video']['uri']
            except Exception as exc:
                logger.warning('Gemini video missing uri response=%s', str(status)[:1200])
                raise GeminiVideoError('missing_video_uri') from exc
            vr = await client.get(uri, headers={'x-goog-api-key': GEMINI_API_KEY})
            if vr.status_code >= 400:
                raise GeminiVideoError(f'download_http_{vr.status_code}')
            if not vr.content:
                raise GeminiVideoError('empty_video')
            return vr.content

    raise GeminiVideoError('timeout')
