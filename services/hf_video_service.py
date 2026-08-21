from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from config import HF_VIDEO_ENABLED, HF_VIDEO_SPACE, HF_VIDEO_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class HfVideoError(RuntimeError):
    pass


def hf_video_available() -> bool:
    return bool(HF_VIDEO_ENABLED and HF_VIDEO_SPACE)


_IMAGE_PARAM_NAMES = {'image', 'img', 'input_image', 'source_image', 'image_input', 'cond_image', 'init_image', 'imageupload'}
_PROMPT_PARAM_NAMES = {'prompt', 'text', 'caption'}
_VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov', '.gif', '.avi', '.mkv'}


def _extract_video_ref(result) -> str | None:
    """Pull a local file path or download URL out of a gradio_client result."""
    stack: list = [result]
    while stack:
        item = stack.pop()
        if item is None:
            continue
        if isinstance(item, dict):
            for key in ('path', 'url', 'value', 'video'):
                if item.get(key):
                    stack.append(item[key])
            continue
        if isinstance(item, (list, tuple)):
            stack.extend(item)
            continue
        if isinstance(item, str) and item.strip():
            value = item.strip()
            if value.startswith(('http://', 'https://')):
                return value
            candidate = Path(value)
            if candidate.exists() and candidate.suffix.lower() in _VIDEO_EXTENSIONS:
                return str(candidate)
    return None


def _resolve_i2v_endpoint(client) -> tuple[str | None, str | None, str | None]:
    """Find the image-to-video endpoint and its image/prompt parameter names.

    Public spaces change their UI often, so the endpoint is discovered from the
    space API schema instead of being hardcoded.
    """
    try:
        api = client.view_api(return_format='dict', print_info=False)
    except Exception as exc:
        raise HfVideoError('view_api_failed') from exc

    named = api.get('named_endpoints') or {}
    unnamed = api.get('unnamed_endpoints') or {}
    for endpoints in (named, unnamed):
        for name, spec in endpoints.items():
            params = spec.get('parameters') or []
            names = [str(p.get('parameter_name') or '').lower() for p in params if isinstance(p, dict)]
            image_param = next((n for n in names if n in _IMAGE_PARAM_NAMES), None)
            if not image_param:
                continue
            prompt_param = next((n for n in names if n in _PROMPT_PARAM_NAMES), None)
            endpoint = name if name in named else None
            return endpoint, image_param, prompt_param
    raise HfVideoError('no_i2v_endpoint')


def _generate_blocking(image_path: str, prompt: str) -> bytes:
    # Imported lazily: gradio_client is heavy and only needed for video jobs.
    from gradio_client import Client, handle_file

    client = Client(HF_VIDEO_SPACE)
    endpoint, image_param, prompt_param = _resolve_i2v_endpoint(client)

    kwargs: dict = {image_param: handle_file(image_path)}
    if prompt_param:
        kwargs[prompt_param] = prompt

    try:
        job = client.submit(**kwargs, api_name=endpoint) if endpoint else client.submit(**kwargs)
        result = job.result(timeout=HF_VIDEO_TIMEOUT_SECONDS)
    except HfVideoError:
        raise
    except TimeoutError as exc:
        raise HfVideoError('timeout') from exc
    except Exception as exc:
        logger.warning('HF video space call failed space=%s error=%s', HF_VIDEO_SPACE, str(exc)[:400])
        raise HfVideoError('space_call_failed') from exc

    video_ref = _extract_video_ref(result)
    if not video_ref:
        logger.warning('HF video space returned no video result=%s', str(result)[:600])
        raise HfVideoError('no_video_result')

    if video_ref.startswith(('http://', 'https://')):
        import httpx
        response = httpx.get(video_ref, timeout=120.0, follow_redirects=True)
        if response.status_code >= 400 or not response.content:
            raise HfVideoError('download_failed')
        return response.content

    data = Path(video_ref).read_bytes()
    if not data:
        raise HfVideoError('empty_video')
    return data


async def animate_image_hf(image_bytes: bytes, mime_type: str = 'image/jpeg', prompt: str | None = None) -> bytes:
    """Free image-to-video via a public Hugging Face Gradio space.

    No payment is required, but the request queues on public GPU servers, so
    expect roughly 1–3 minutes. Callers should warn the user about the wait.
    """
    if not hf_video_available():
        raise HfVideoError('video_disabled')
    if not image_bytes:
        raise HfVideoError('empty_image')

    prompt = prompt or (
        'Animate this exact photo of the same adult woman. Preserve her identity, face, hair, body proportions, '
        'clothing and scene. Natural subtle smile, one or two blinks, gentle breathing, tiny head movement and '
        'realistic handheld camera micro-motion. No wardrobe change, no body transformation, no extra people, '
        'no sexual action, no nudity, no text or logos. Photorealistic and calm.'
    )
    suffix = '.png' if 'png' in (mime_type or '') else '.jpg'
    fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix='annabot_hf_video_')
    try:
        with os.fdopen(fd, 'wb') as tmp:
            tmp.write(image_bytes)
        return await asyncio.to_thread(_generate_blocking, tmp_path, prompt)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
