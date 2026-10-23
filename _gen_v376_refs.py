"""V3.76.0 one-off: canonical references for the scenario-card girls.

Runs on the owner's PC (the cloud container cannot reach SpicyAPI):
    python _gen_v376_refs.py <file-with-SPICYAPI_KEY> [girl ...]
For each girl: a face portrait (Seedream 5.0 Pro text-to-image), then her
full look from that face (Seedream edit), saved straight into
data/references/<folder>/00_<folder>_canonical_face.png and
01_<folder>_canonical_look.png. ~$0.07 a girl. Stdlib only.
"""
import json
import pathlib
import re
import sys
import time
import urllib.request
import uuid

from _install_v376_girls import GIRLS

ROOT = pathlib.Path(__file__).resolve().parent
raw = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
m = re.search(r'SPICYAPI_KEY\s*=\s*["\']?([^\s"\']+)', raw)
KEY = m.group(1) if m else raw.strip()
BASE = 'https://api.spicyapi.ai/api/v1'
ONLY = set(sys.argv[2:])

QUALITY = (' Photorealistic smartphone photo, natural skin texture, sharp focus on the eyes, '
           'anatomically correct: exactly two arms and two hands, five fingers on each hand. '
           'Adult woman, one person only, fully dressed, no nudity, no text, no watermark, no logo.')


def call(method, path, body=None):
    req = urllib.request.Request(
        BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json',
                 'Idempotency-Key': str(uuid.uuid4())})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    if d.get('code') not in (200, 201, 202):
        raise RuntimeError(d)
    return d.get('data', {})


def upload(data: bytes, ctype: str) -> str:
    slot = call('POST', '/common/upload-url', {'contentType': ctype, 'bytes': len(data)})
    put = urllib.request.Request(slot['uploadUrl'], data=data, method='PUT', headers={'Content-Type': ctype})
    urllib.request.urlopen(put, timeout=60).read()
    return call('POST', f"/files/{slot['fileId']}/commit", {})['uri']


def render(model: str, prompt: str, refs=None) -> bytes:
    inp = {'prompt': prompt, 'aspect_ratio': '3:4', 'resolution': '1k', 'output_format': 'png',
           'enable_thinking': True}
    if refs:
        inp['image_urls'] = refs
    tid = call('POST', '/jobs/createTask', {'model': model, 'input': inp})['taskId']
    for _ in range(100):
        time.sleep(3)
        info = call('GET', f'/jobs/recordInfo?taskId={tid}')
        if info.get('state') == 'succeeded':
            url = next(a['url'] for a in info['output']['assets'] if a.get('url'))
            return urllib.request.urlopen(url, timeout=60).read()
        if info.get('state') in ('failed', 'expired', 'canceled'):
            raise RuntimeError(f"{info.get('errorCode')} {info.get('errorMessage')}")
    raise RuntimeError('timeout')


for g in GIRLS:
    f = g['folder']
    if ONLY and f not in ONLY:
        continue
    folder = ROOT / 'data' / 'references' / f
    folder.mkdir(parents=True, exist_ok=True)
    face_path = folder / f'00_{f}_canonical_face.png'
    look_path = folder / f'01_{f}_canonical_look.png'
    try:
        if not face_path.exists():
            face_path.write_bytes(render('bytedance/seedream-5.0-pro/text-to-image', g['face'] + '.' + QUALITY))
            print('ok', face_path)
        if not look_path.exists():
            uri = upload(face_path.read_bytes(), 'image/png')
            prompt = ('The same woman as in the reference image: keep her exact face, eyes, nose, lips, hair color '
                      f'and length, skin tone. {g["look"]}. Full look, knees up, {g["look_prompt"]}.' + QUALITY)
            look_path.write_bytes(render('bytedance/seedream-5.0-pro/edit', prompt, [uri]))
            print('ok', look_path)
    except Exception as e:  # keep going with the other girls
        print('error', f, e)
