from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from config import HF_VIDEO_ENABLED, HF_VIDEO_SPACE, HF_VIDEO_TIMEOUT_SECONDS, HF_VIDEO_FALLBACK_SPACES

logger = logging.getLogger(__name__)


class HfVideoError(RuntimeError):
    pass


def hf_video_available() -> bool:
    return bool(HF_VIDEO_ENABLED and HF_VIDEO_SPACE)


_IMAGE_PARAM_NAMES = {
    'image', 'img', 'input_image', 'source_image', 'image_input', 'cond_image',
    'init_image', 'imageupload', 'input_img', 'source_img', 'first_frame',
    'first_frame_image', 'image_path', 'input_picture', 'picture',
}
_PROMPT_PARAM_NAMES = {'prompt', 'text', 'caption', 'description', 'text_prompt', 'input_text'}
_VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov', '.gif', '.avi', '.mkv'}


def _is_error_string(value: str) -> bool:
    """Detect when the space returned a text error instead of a video."""
    lower = value.lower()
    error_markers = ('error', 'exception', 'traceback', 'failed', 'invalid input',
                     'nsfw', 'content policy', 'unsupported', 'not allowed')
    return any(marker in lower for marker in error_markers)


def _extract_video_ref(result) -> str | None:
    """Pull a local file path or download URL out of a gradio_client result."""
    stack: list = [result]
    while stack:
        item = stack.pop()
        if item is None:
            continue
        if isinstance(item, dict):
            for key in ('path', 'url', 'value', 'video', 'video_url', 'output', 'output_video', 'file'):
                if item.get(key):
                    stack.append(item[key])
            continue
        if isinstance(item, (list, tuple)):
            stack.extend(item)
            continue
        # pathlib.Path from newer gradio_client versions.
        if hasattr(item, '__fspath__'):
            try:
                p = Path(os.fspath(item))
                if p.exists() and p.suffix.lower() in _VIDEO_EXTENSIONS:
                    return str(p)
            except Exception:
                pass
            continue
        if isinstance(item, str) and item.strip():
            value = item.strip()
            if value.startswith(('http://', 'https://')):
                return value
            candidate = Path(value)
            if candidate.exists() and candidate.suffix.lower() in _VIDEO_EXTENSIONS:
                return str(candidate)
        # Dataclass / NamedTuple-like result objects from some spaces.
        if not isinstance(item, (str, dict, list, tuple, bytes)):
            for attr in ('path', 'url', 'video', 'value', 'video_url', 'output', 'file'):
                candidate = getattr(item, attr, None)
                if candidate is not None:
                    stack.append(candidate)
    return None


def _resolve_i2v_endpoint(client) -> tuple[str | None, str | None, str | None]:
    """Find the image-to-video endpoint and its image/prompt parameter names.

    Public spaces change their UI often, so the endpoint is discovered from the
    space API schema instead of being hardcoded.  When no parameter name
    matches the known sets, a type/label-based fallback is tried before giving
    up — many spaces use generic parameter labels with empty ``parameter_name``.
    """
    try:
        api = client.view_api(return_format='dict', print_info=False)
    except Exception as exc:
        raise HfVideoError('view_api_failed') from exc

    named = api.get('named_endpoints') or {}
    unnamed = api.get('unnamed_endpoints') or {}

    # Log a compact schema summary so the owner can see what the space exposes.
    try:
        summary_parts = []
        for label, endpoints in (('named', named), ('unnamed', unnamed)):
            for name, spec in endpoints.items():
                params = spec.get('parameters') or []
                names = [str(p.get('parameter_name') or p.get('label') or '?').lower() for p in params if isinstance(p, dict)]
                summary_parts.append(f'{label}:{name}({len(params)} params: {",".join(names[:6])})')
        logger.info('HF video space schema: %s', '; '.join(summary_parts) or 'empty')
    except Exception:
        pass

    # Pass 1: match by known parameter name.
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

    # Pass 2: match by parameter label or type hint (spaces often expose a
    # ``label`` like "Image" while ``parameter_name`` is empty or generic).
    _IMAGE_LABEL_HINTS = {'image', 'img', 'picture', 'photo', 'input image', 'source image', 'first frame'}
    _PROMPT_LABEL_HINTS = {'prompt', 'text', 'caption', 'description'}
    for endpoints in (named, unnamed):
        for name, spec in endpoints.items():
            params = spec.get('parameters') or []
            image_param = None
            prompt_param = None
            for p in params:
                if not isinstance(p, dict):
                    continue
                pname = str(p.get('parameter_name') or '').lower()
                plabel = str(p.get('label') or '').lower().strip()
                ptype = str(p.get('type') or p.get('python_type') or '').lower()
                if not image_param and (plabel in _IMAGE_LABEL_HINTS or 'image' in ptype or 'file' in ptype):
                    image_param = pname or plabel
                elif not prompt_param and (plabel in _PROMPT_LABEL_HINTS or 'text' in ptype or 'str' in ptype):
                    prompt_param = pname or plabel
            if image_param:
                endpoint = name if name in named else None
                return endpoint, image_param, prompt_param

    raise HfVideoError('no_i2v_endpoint')


def _generate_blocking(image_path: str, prompt: str, space: str = HF_VIDEO_SPACE) -> bytes:
    # Imported lazily: gradio_client is heavy and only needed for video jobs.
    from gradio_client import Client, handle_file

    last_error: Exception | None = None
    # The free public Gradio space is a shared, best-effort resource. A cold
    # start or a momentarily busy queue is common and usually resolves on a
    # fresh connection, so we retry the submit-and-wait cycle ONCE — but only
    # for quick setup/connection failures. A timeout is NOT retried, because
    # retrying it would double the user's wait beyond the promised 1–3 min.
    for attempt in range(2):
        try:
            client = Client(space)
            endpoint, image_param, prompt_param = _resolve_i2v_endpoint(client)

            kwargs: dict = {image_param: handle_file(image_path)}
            if prompt_param:
                kwargs[prompt_param] = prompt

            job = client.submit(**kwargs, api_name=endpoint) if endpoint else client.submit(**kwargs)
            result = job.result(timeout=HF_VIDEO_TIMEOUT_SECONDS)
            break
        except TimeoutError as exc:
            last_error = HfVideoError('timeout')
            logger.warning('HF video attempt %s/2 timed out space=%s (not retrying to avoid doubling wait)', attempt + 1, space)
            break
        except HfVideoError as exc:
            last_error = exc
            logger.warning('HF video attempt %s/2 failed space=%s error=%s', attempt + 1, space, exc)
            continue
        except Exception as exc:
            last_error = HfVideoError('space_call_failed')
            logger.warning('HF video attempt %s/2 call failed space=%s error=%s', attempt + 1, space, str(exc)[:400])
            continue
    else:
        raise last_error or HfVideoError('space_call_failed')

    video_ref = _extract_video_ref(result)
    if not video_ref:
        # Surface the raw result so the owner log shows exactly what the space
        # returned — this is the single most useful diagnostic when a public
        # space changes its output format.
        logger.warning('HF video space returned no video, raw result=%s', str(result)[:800])
        # Detect error messages disguised as a normal result string.
        if isinstance(result, str) and _is_error_string(result):
            raise HfVideoError(f'space_error:{result[:200]}')
        if isinstance(result, (list, tuple)):
            for item in result:
                if isinstance(item, str) and _is_error_string(item):
                    raise HfVideoError(f'space_error:{item[:200]}')
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
        # Walk the main space plus fallbacks: a dead/overloaded public space
        # should fail the whole animation only when every candidate failed.
        spaces = [HF_VIDEO_SPACE] + [s for s in HF_VIDEO_FALLBACK_SPACES if s != HF_VIDEO_SPACE]
        last_error: Exception | None = None
        for idx, space in enumerate(spaces):
            try:
                if idx > 0:
                    logger.info('HF video falling back to space=%s after %s failure(s)', space, idx)
                return await asyncio.to_thread(_generate_blocking, tmp_path, prompt, space)
            except HfVideoError as exc:
                last_error = exc
                logger.warning('HF video space=%s failed error=%s', space, exc)
                continue
        raise last_error or HfVideoError('all_spaces_failed')
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
