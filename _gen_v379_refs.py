"""V3.79.0 one-off: canonical references for the six new roster girls.

Owner sent six photos as *type* references (hair, styling, vibe, setting).
Faces here are new and original: no reference image is ever sent to the
model, only text, so nobody real gets cloned.

Runs on the owner's PC (the cloud container cannot reach SpicyAPI):
    python _gen_v379_refs.py <file-with-SPICYAPI_KEY> [girl ...]
Saves data/references/<folder>/00_<folder>_canonical_face.png and
01_<folder>_canonical_look.png (look = edit from her face). Stdlib only.
"""
import json
import pathlib
import re
import sys
import time
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parent
raw = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
m = re.search(r'SPICYAPI_KEY\s*=\s*["\']?([^\s"\']+)', raw)
KEY = m.group(1) if m else raw.strip()
BASE = 'https://api.spicyapi.ai/api/v1'
ONLY = set(sys.argv[2:])

QUALITY = (' Photorealistic smartphone photo, natural skin texture with pores, sharp focus on the eyes, '
           'original fictional woman with a unique face, not a celebrity, '
           'anatomically correct: exactly two arms and two hands, five fingers on each hand. '
           'Adult woman, one person only, fully dressed, no nudity, no text, no watermark, no logo.')
SEXY = (' Sensual glamour mood: confident seductive body language, eye contact with the viewer, '
        'body-hugging outfit that shows off her curves.')

GIRLS = [
    dict(folder='vlada',
         face='Close-up selfie portrait of an adult woman, 23 years old, very long straight platinum blonde hair '
              'with a middle part, light grey-blue eyes, sharp black winged eyeliner, heart-shaped face, small '
              'slightly upturned nose, high cheekbones, full glossy nude-pink lips, long milky almond nails, thin black '
              'velvet choker, black long-sleeve scoop-neck bodysuit, playful wink with a fingertip touching her lower '
              'lip, dark moody bedroom background',
         look='Full look, knees up: same black long-sleeve scoop-neck bodysuit with high-waisted black leather mini '
              'skirt, standing by a dark bedroom wall in dim warm light, one hand in her hair, smirking at the viewer',
         body='a slim waist, round hips and a full natural bust (D cup)'),
    dict(folder='milana',
         face='Portrait photo of an adult woman, 26 years old, very long sleek straight chestnut-brown hair, striking '
              'bright blue eyes, sharply arched dark brows, oval face, straight nose, full plump lips with nude '
              'lipstick, flawless glam makeup, fitted beige ribbed turtleneck sweater, sitting in a cozy restaurant '
              'by the window, warm bokeh lights behind, calm cool confident gaze',
         look='Full look, knees up: tight beige ribbed turtleneck sweater dress, standing by the bar of an evening '
              'restaurant, one hand on the counter, cool inviting half-smile',
         body='a very voluptuous hourglass figure with a large full bust (F cup) and a narrow waist'),
    dict(folder='polina',
         face='Portrait photo of an adult woman, 22 years old, wavy golden honey-blonde hair with darker roots, '
              'sun-kissed tanned skin, hazel-green eyes, soft feathered brows, small nose, full soft lips with a lazy '
              'sleepy smile, light bronzed makeup, cream ribbed cotton camisole, sitting on a messy white bed in a '
              'bright airy bedroom with a rattan lamp, soft morning light',
         look='Full look, knees up: cream ribbed camisole and soft cream lounge shorts, sitting on a messy white bed '
              'leaning back on her hands, bright morning light, sleepy flirty look at the viewer',
         body='a toned tanned hourglass build with round hips and a natural full bust (C cup)'),
    dict(folder='dasha',
         face='Portrait photo of an adult woman, 25 years old, dark brown hair in a loose low messy bun with long '
              'face-framing strands and wispy curtain bangs, lots of natural freckles across the nose and cheeks, '
              'warm amber-brown eyes, natural thick brows, soft round face, minimal makeup, thin gold chain necklace, '
              'black ribbed tank top, dim bedroom with grey textured wallpaper, calm direct slightly mysterious gaze',
         look='Full look, knees up: black ribbed tank top and loose high-waisted grey sweatpants, sitting on the arm '
              'of a sofa in a dim evening bedroom, head tilted, quiet teasing look',
         body='a soft curvy build with wide hips and a very full natural bust (E cup)'),
    dict(folder='kamila',
         face='Selfie photo of an adult woman, 22 years old, very long straight glossy jet-black hair, honey-brown '
              'eyes, thick dark groomed brows, olive skin, softly angular face, full lips in a playful kiss pout, '
              'gold coin pendant necklace, black tank top, sitting in the driver seat of a car with the seatbelt on, '
              'pink sunset over a desert highway through the window, one hand resting on her head',
         look='Full look, knees up: black fitted tank top and light blue denim mini skirt, leaning against the side '
              'of a black car at a roadside at pink sunset, keys in her hand, bold confident look',
         body='a curvy hourglass figure with wide hips and a large full bust (E cup)'),
    dict(folder='rita',
         face='Portrait photo of an adult woman, 24 years old, shoulder-length layered copper-red hair with soft '
              'volume, pale skin with light freckles, bright green eyes, soft rounded nose, natural peach lips, small '
              'gold hoop earrings, fitted charcoal-grey turtleneck sweater, plain light grey studio background, '
              'bright cheerful open laugh',
         look='Full look, knees up: fitted charcoal-grey turtleneck and a short plaid skirt with black tights, '
              'sitting on the edge of a desk with a laptop in a sunny apartment, laughing and looking at the viewer',
         body='a slim hourglass build with a natural full bust (C cup)'),
]


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


if __name__ == '__main__':
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
                prompt = ('The same woman as in the reference image: keep her exact face, eyes, nose, lips, hair '
                          f'color and length, skin tone, freckles. Her figure: {g["body"]}. {g["look"]}.'
                          + SEXY + QUALITY)
                look_path.write_bytes(render('bytedance/seedream-5.0-pro/edit', prompt, [uri]))
                print('ok', look_path)
        except Exception as e:  # keep going with the other girls
            print('error', f, e)
