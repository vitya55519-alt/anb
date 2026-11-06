"""V3.114.0 one-off: catalogue card pictures for «👗 Гардероб».

Owner: «картинка — девушка стоит, возьмём Анну, и она во всех нарядах. Главное,
чтобы модель не плавала: в одной больше грудь, в другой меньше». So every card
is an edit of the SAME two canonical Anna references (face + look) with one
fixed pose, one room, one camera and one written body lock; only the garment
(or the room thing) changes.

Runs on the owner's PC (the cloud container cannot reach SpicyAPI):
    python _gen_v3114_wardrobe_art.py <file-with-SPICYAPI_KEY> [item_id ...]
Writes webapp/art/wd_<item>.jpg (600x800) and a review sheet
%USERPROFILE%/Desktop/wardrobe_cards.jpg. Existing cards are skipped; delete a
card file to re-render it.
"""
import io
import pathlib
import sys

ARGS = sys.argv[2:]
sys.argv = sys.argv[:2]  # _gen_v379_refs reads the key from argv[1]
import _gen_v379_refs as g  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, str(g.ROOT))
from services.wardrobe_catalog import ITEMS  # noqa: E402  (pure data, no DB)

EDIT = 'bytedance/seedream-5.0-pro/edit'
REF = g.ROOT / 'data' / 'references' / 'anna'
OUT = g.ROOT / 'webapp' / 'art'
SHEET = pathlib.Path.home() / 'Desktop' / 'wardrobe_cards.jpg'

KEEP = ('The same woman as in both reference images: keep her exact face, eyes, brows, nose, lips, '
        'dark-brown brunette hair and skin tone. ')
BODY = ('Her figure is identical in every picture of this series: distinctly slim and fit body, narrow waist, '
        'full bust with silicone implants (Russian size 5, E cup), the same hips and legs; never bigger or smaller. ')
POSE = ('Full body from head to feet, standing straight facing the camera, weight on one leg, one hand relaxed at '
        'her side, the other lightly touching her hair, soft warm smile, eye contact. She stands in a bright cozy '
        'bedroom with a white wall, a light wooden floor and a tall mirror, soft natural daylight. Camera at chest '
        'height, vertical 3:4 frame, the same framing as a catalogue photo. ')
CLOSE = ('Waist-up portrait facing the camera, one hand lightly touching her collarbone, soft warm smile, the same '
         'bright cozy bedroom with a white wall behind her, soft natural daylight. ')
ROOM = ('She sits on the edge of her bed in her cozy bedroom with a white wall and a light wooden floor, soft warm '
        'evening light, relaxed happy smile, eye contact. The room clearly shows: ')
QUALITY = (' Photorealistic smartphone photo, natural skin texture, sharp focus, anatomically correct: exactly two '
           'arms and two hands, five fingers on each hand. Adult woman, one person only, no nudity, no text, '
           'no watermark, no logo.')


def prompt_for(item) -> str:
    if item.kind == 'room':
        extra = ' She holds the small fluffy grey kitten in her arms.' if item.id == 'kitten' else ''
        return KEEP + BODY + ROOM + item.prompt + '. She wears a cozy cream knit sweater and light jeans.' + extra + QUALITY
    if item.kind == 'jewel':
        return KEEP + BODY + CLOSE + f'She wears {item.prompt}, clearly visible, with a plain white fitted top.' + QUALITY
    wear = item.prompt
    if item.kind == 'adult':
        wear += ', tasteful boudoir catalogue style, the lingerie fully covers her, no nipples'
    return KEEP + BODY + POSE + f'She wears {wear}.' + QUALITY


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    refs = [g.upload((REF / n).read_bytes(), 'image/png')
            for n in ('00_anna_canonical_face_v3.png', '01_anna_canonical_look_v3.png')]
    for item in ITEMS:
        if ARGS and item.id not in ARGS:
            continue
        path = OUT / f'wd_{item.id}.jpg'
        if path.exists():
            continue
        try:
            raw = g.render(EDIT, prompt_for(item), refs)
            im = Image.open(io.BytesIO(raw)).convert('RGB')
            im = im.resize((600, 800), Image.LANCZOS) if abs(im.width / im.height - 0.75) < 0.02 else im.resize((600, round(600 * im.height / im.width)), Image.LANCZOS)
            im.save(path, 'JPEG', quality=86, optimize=True)
            print('ok', path.name, flush=True)
        except Exception as e:  # keep going with the rest
            print('error', item.id, e, flush=True)
    make_sheet()


def make_sheet() -> None:
    cards = [(i, OUT / f'wd_{i.id}.jpg') for i in ITEMS if (OUT / f'wd_{i.id}.jpg').exists()]
    if not cards:
        return
    cols, w, h = 6, 300, 400
    rows = (len(cards) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * w, rows * h), (26, 16, 35))
    for n, (_i, p) in enumerate(cards):
        im = Image.open(p).convert('RGB').resize((w, h))
        sheet.paste(im, ((n % cols) * w, (n // cols) * h))
    sheet.save(SHEET, 'JPEG', quality=85)
    print('sheet', SHEET, len(cards), flush=True)


if __name__ == '__main__':
    main()
