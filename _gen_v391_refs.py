"""V3.91.0 one-off: face variants and canonical references for Агата.

The owner's photos were only an appearance prompt; no reference image is
ever sent to the model, only text, so nobody real gets cloned.

Runs on the owner's PC (the cloud container cannot reach SpicyAPI):
    python _gen_v391_refs.py <file-with-SPICYAPI_KEY>          # 3 variants
    python _gen_v391_refs.py <file-with-SPICYAPI_KEY> pick 2   # make v2 canonical
Variants go to data/references/_agata_variants/; «pick» copies one to
data/references/agata/00_agata_canonical_face.png + 01_agata_canonical_look.png.
"""
import pathlib
import shutil
import sys

ARGS = sys.argv[1:]
sys.argv = sys.argv[:2]  # _gen_v379_refs reads the key from argv[1] and filters by argv[2:]
import _gen_v379_refs as g  # noqa: E402

ROOT = g.ROOT
VAR = ROOT / 'data' / 'references' / '_agata_variants'

QUALITY = (' High-end glamour smartphone photo, flawless smooth glam skin, sharp focus on the eyes, '
           'original fictional woman with a unique face, not a celebrity, '
           'anatomically correct: exactly two arms and two hands, five fingers on each hand. '
           'Adult woman, one person only, fully dressed, no nudity, no text, no watermark, no logo.')
SEXY = (' Tender sensual mood: soft inviting smile, eye contact with the viewer, '
        'body-hugging outfit that shows off her curves.')
BODY = 'a very voluptuous hourglass figure with a tiny cinched waist, wide round hips and a very large full bust (F cup)'
COMMON = ('adult woman, 23 years old, very pale porcelain skin, big dark doe eyes with long lashes and soft smoky '
          'liner, small soft nose, full plump lips with matte dark plum-black lipstick, black spiked choker with a '
          'thin silver chain')

VARIANTS = [
    dict(face=f'Selfie portrait of an {COMMON}, long straight glossy jet-black hair with thick blunt bangs, black '
              'mesh long-sleeve top, lying on a bed with dark sheets, chin resting on her hand, dim bedroom lit by '
              'candles, tender dreamy smile',
         look='Full look, knees up: black corset top with sheer black mesh sleeves, black leather mini skirt and '
              'black stockings, standing by a candlelit bedroom wall, one hand in her hair, tender inviting look'),
    dict(face=f'Portrait photo of an {COMMON}, shoulder-length straight jet-black hair with thick blunt bangs, black '
              'fitted scoop-neck top, sitting at a desk with a studio microphone and headphones around her neck, '
              'dim room with purple fairy lights and candles, soft shy smile, head slightly tilted',
         look='Full look, knees up: black fitted corset dress with lace trim and black fishnet stockings, sitting on '
              'the edge of a bed next to a studio microphone, candles around, leaning forward with a tender smile'),
    dict(face=f'Selfie portrait of an {COMMON}, very long straight blue-black hair with blunt bangs, black velvet '
              'top with a square neckline, silver chains, at a dark gothic party with red light behind her, '
              'sweet playful smile with a glance from under the bangs',
         look='Full look, knees up: black velvet corset top with mesh long sleeves and a black pleated mini skirt '
              'with a belt of silver rings, black thigh-high socks, standing in a dark club with red light, '
              'looking over her shoulder with a soft smile'),
]


def make_variants() -> None:
    VAR.mkdir(parents=True, exist_ok=True)
    for i, v in enumerate(VARIANTS, 1):
        face, look = VAR / f'agata_v{i}_face.png', VAR / f'agata_v{i}_look.png'
        try:
            if not face.exists():
                face.write_bytes(g.render('bytedance/seedream-5.0-pro/text-to-image', v['face'] + '.' + QUALITY))
                print('ok', face)
            if not look.exists():
                uri = g.upload(face.read_bytes(), 'image/png')
                prompt = ('The same woman as in the reference image: keep her exact face, eyes, nose, lips, '
                          f'dark lipstick, black hair with bangs, pale skin. Her figure: {BODY}. {v["look"]}.'
                          + SEXY + QUALITY)
                look.write_bytes(g.render('bytedance/seedream-5.0-pro/edit', prompt, [uri]))
                print('ok', look)
        except Exception as e:  # keep going with the other variants
            print('error', i, e)


def pick(n: int) -> None:
    out = ROOT / 'data' / 'references' / 'agata'
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(VAR / f'agata_v{n}_face.png', out / '00_agata_canonical_face.png')
    shutil.copyfile(VAR / f'agata_v{n}_look.png', out / '01_agata_canonical_look.png')
    print('picked', n)


if __name__ == '__main__':
    if len(ARGS) >= 3 and ARGS[1] == 'pick':
        pick(int(ARGS[2]))
    else:
        make_variants()
