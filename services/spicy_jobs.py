"""V3.72.0: the bits every SpicyAPI job shares — free file upload (spicy://)
and one createTask → recordInfo poll loop that hands back the first asset.

Shapes verified on the owner's PC (2026-10-23): createTask answers
``{taskId}``; recordInfo answers ``{state, output: {assets: [{url, mime}]},
cost, errorCode, errorMessage}``; asset urls are signed and expire in ~20 min,
so the bytes are downloaded right away. Failed jobs are not billed.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

import aiohttp

logger = logging.getLogger(__name__)


class SpicyJobError(RuntimeError):
    pass


async def upload(data: bytes, content_type: str) -> str:
    """Free upload → ``spicy://f/...`` URI (deleted once the job that used it
    finishes, so upload again per job)."""
    from services.private_photo_service import _spicyapi_call
    slot = await _spicyapi_call('POST', '/common/upload-url',
                                json={'contentType': content_type, 'bytes': len(data)})
    upload_url, file_id = slot.get('uploadUrl'), slot.get('fileId')
    if not upload_url or not file_id:
        raise SpicyJobError(f'upload_slot: {slot}'[:200])
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
        async with s.put(upload_url, data=data, headers={'Content-Type': content_type}) as resp:
            if resp.status >= 300:
                raise SpicyJobError(f'upload_put_{resp.status}')
    done = await _spicyapi_call('POST', f'/files/{file_id}/commit', json={})
    uri = done.get('uri')
    if not uri:
        raise SpicyJobError(f'upload_commit: {done}'[:200])
    return uri


async def run(model: str, input_block: dict, *, timeout: float, first_wait: float = 3.0) -> tuple[bytes, str, float]:
    """Run one job to the end: (asset bytes, mime, billed cost in USD).

    Raises SpicyJobError on a refused, failed or timed-out job."""
    from services.private_photo_service import _spicyapi_call
    try:
        task = await _spicyapi_call(
            'POST', '/jobs/createTask',
            headers={'Idempotency-Key': str(uuid.uuid4())},
            json={'model': model, 'input': input_block},
        )
    except Exception as exc:
        raise SpicyJobError(f'create: {str(exc)[:200]}') from exc
    task_id = task.get('taskId')
    if not task_id:
        raise SpicyJobError('no_task_id')
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    wait = first_wait
    state = 'queued'
    while loop.time() < deadline:
        await asyncio.sleep(wait)
        wait = min(wait * 1.2, 6.0)
        try:
            info = await _spicyapi_call('GET', f'/jobs/recordInfo?taskId={task_id}')
        except Exception as exc:
            logger.warning('SpicyAPI poll failed %s: %s', task_id, exc)
            continue
        state = info.get('state')
        if state == 'succeeded':
            try:
                cost = float(info.get('cost') or 0)
            except (TypeError, ValueError):
                cost = 0.0
            assets = (info.get('output') or {}).get('assets') or []
            asset = next((a for a in assets if a.get('url')), None)
            if not asset:
                raise SpicyJobError('no_asset')
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
                async with s.get(asset['url']) as resp:
                    if resp.status != 200:
                        raise SpicyJobError(f'download_{resp.status}')
                    return await resp.read(), asset.get('mime') or '', cost
        if state in ('failed', 'expired', 'canceled'):
            raise SpicyJobError(f"{state}: {info.get('errorCode') or info.get('errorMessage')}"[:200])
    raise SpicyJobError(f'timeout_{state}')
