"""V3.109.0 one-off: face variants and canonical references for Джина and Лана.

Джина: the owner sent screenshots of a real girl from YouTube Shorts as a style
prompt only. Her face is new: text only, no image is sent to the model.
Лана: the owner's own ComfyUI renders (synthetic, 25 y.o. per the file metadata)
give her face, so that one file IS sent as a reference.

Runs on the owner's PC (the cloud container cannot reach SpicyAPI):
    python _gen_v3109_refs.py <key-file> <c1_face.png>             # variants
    python _gen_v3109_refs.py <key-file> pick jina 2               # v2 canonical
    python _gen_v3109_refs.py <key-file> mix lana 1 2              # v1 face, v2 outfit
Variants go to %USERPROFILE%/Desktop/new_girls_preview, not to the repo.
"""
import pathlib
import shutil
import sys

ARGS = sys.argv[1:]
sys.argv = sys.argv[:2]  # _gen_v379_refs reads the key from argv[1], filters by argv[2:]
import _gen_v379_refs as g  # noqa: E402

VAR = pathlib.Path.home() / 'Desktop' / 'new_girls_preview'
T2I = 'bytedance/seedream-5.0-pro/text-to-image'
EDIT = 'bytedance/seedream-5.0-pro/edit'
QUALITY = (' High-end glamour smartphone photo, flawless smooth glam skin, sharp focus on the eyes, '
           'original fictional woman with a unique face, not a celebrity, '
           'anatomically correct: exactly two arms and two hands, five fingers on each hand. '
           'Adult woman, mature grown-up features, one person only, fully dressed, no nudity, no text, '
           'no watermark, no logo.')
SEXY = (' Confident flirty mood: eye contact with the viewer, body-hugging outfit that shows off her curves.')

JINA_FACE = ('adult Korean woman, 24 years old, mature confident face, very long loose wavy glossy jet-black hair with '
             'soft wispy see-through bangs, elegant almond eyes with a thin dark liner, softly defined cheekbones, '
             'small straight nose, full glossy rose lips, K-beauty glam makeup')
JINA_BODY = 'a slim hourglass figure with a narrow waist, round hips, long legs and a full natural bust (D cup)'
JINA_OUTFIT = ('fitted white ribbed long-sleeve crop top with a tiny black heart print, slightly off one shoulder, and low-rise '
               'black mini shorts with silver eyelets and a studded black belt with a big rhinestone buckle')
LANA_BODY = ('an extremely voluptuous hourglass figure with a very narrow waist, wide round hips and huge, perfectly '
             'round, high and firm augmented silicone breast implants (Russian size 8, H cup), toned sun-kissed skin')
LANA_KEEP = ('The same woman as in the reference image: keep her exact face, blue eyes with amber centers, brows, '
             'nose and lips. ')

VARIANTS = {
    'jina': [
        dict(face=f'Selfie portrait of an {JINA_FACE}, {JINA_OUTFIT}, in a bright modern Seoul cafe, playful smile, head tilted',
             look='Full look, knees up: same outfit, posing on an evening city street with neon signs, one fingertip touching her lower lip, playful smile'),
        dict(face=f'Portrait photo of an {JINA_FACE}, thin silver necklace, {JINA_OUTFIT}, dance studio with mirrors, sweet confident smirk',
             look='Full look, knees up: same outfit, standing in a cozy beige bedroom with framed fruit prints and a small round table lamp, fingertip at her lips, confident smirk'),
        dict(face=f'Close-up selfie of an {JINA_FACE}, small silver hoop earrings, {JINA_OUTFIT}, her cozy room with warm fairy lights, biting her lip with a teasing look',
             look='Full look, knees up: same outfit, leaning on a desk with a ring light in her cozy room, looking over her shoulder with a teasing smile'),
    ],
    'lana': [
        dict(face=LANA_KEEP + 'Long sleek straight dark chestnut-brown hair with a side part. Waist-up selfie portrait, adult woman, 26 years old, tight black glossy top with a deep neckline, gold hoop earrings, luxury bedroom with a big window, golden hour light, soft confident smile',
             look='Full look, knees up: tight glossy black vinyl jumpsuit with thin straps and a deep neckline, gold hoop earrings, sitting on the edge of a white bed in a luxury city apartment, leaning on one hand, flirty smirk'),
        dict(face=LANA_KEEP + 'Long glossy chestnut-brown waves, full glam makeup with sharp winged eyeliner, lash extensions and overlined glossy lips. Portrait, adult woman, 26 years old, black glossy corset top, gold hoop earrings, luxury apartment, evening window light, sultry smirk',
             look='Full look, knees up: glossy black vinyl corset dress with thin straps, gold hoop earrings, standing by a big window of a luxury apartment at night, one hand on her hip, sultry smirk'),
    ],
}


def make_variants(c1: str) -> None:
    VAR.mkdir(parents=True, exist_ok=True)
    c1_uri = None
    for name, items in VARIANTS.items():
        for i, v in enumerate(items, 1):
            face, look = VAR / f'{name}_v{i}_face.png', VAR / f'{name}_v{i}_look.png'
            body = JINA_BODY if name == 'jina' else LANA_BODY
            try:
                if not face.exists():
                    if name == 'lana':
                        c1_uri = c1_uri or g.upload(pathlib.Path(c1).read_bytes(), 'image/png')
                        face.write_bytes(g.render(EDIT, v['face'] + '.' + QUALITY, [c1_uri]))
                    else:  # text only: nobody real gets cloned
                        face.write_bytes(g.render(T2I, v['face'] + '.' + QUALITY))
                    print('ok', face.name, flush=True)
                if not look.exists():
                    uri = g.upload(face.read_bytes(), 'image/png')
                    prompt = ('The same woman as in the reference image: keep her exact face, eyes, nose, lips, '
                              f'hair color and length, skin tone. Her figure: {body}. {v["look"]}.' + SEXY + QUALITY)
                    look.write_bytes(g.render(EDIT, prompt, [uri]))
                    print('ok', look.name, flush=True)
            except Exception as e:  # keep going with the other variants
                print('error', name, i, e, flush=True)


def mix(name: str, face_n: int, look_n: int) -> None:
    """Owner: «лицо 1, фигура 2»: her face from one variant, outfit and pose of
    another, rendered fresh from that face."""
    out = g.ROOT / 'data' / 'references' / name
    out.mkdir(parents=True, exist_ok=True)
    face = VAR / f'{name}_v{face_n}_face.png'
    mixed = VAR / f'{name}_v{face_n}x{look_n}_look.png'
    body = JINA_BODY if name == 'jina' else LANA_BODY
    if not mixed.exists():
        uri = g.upload(face.read_bytes(), 'image/png')
        prompt = ('The same woman as in the reference image: keep her exact face, eyes, nose, lips, '
                  f'hair color and length, skin tone. Her figure: {body}. {VARIANTS[name][look_n - 1]["look"]}.'
                  + SEXY + QUALITY)
        mixed.write_bytes(g.render(EDIT, prompt, [uri]))
    shutil.copyfile(face, out / f'00_{name}_canonical_face.png')
    shutil.copyfile(mixed, out / f'01_{name}_canonical_look.png')
    print('mixed', name, face_n, look_n)


def pick(name: str, n: int) -> None:
    out = g.ROOT / 'data' / 'references' / name
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(VAR / f'{name}_v{n}_face.png', out / f'00_{name}_canonical_face.png')
    shutil.copyfile(VAR / f'{name}_v{n}_look.png', out / f'01_{name}_canonical_look.png')
    print('picked', name, n)


if __name__ == '__main__':
    if len(ARGS) >= 5 and ARGS[1] == 'mix':
        mix(ARGS[2], int(ARGS[3]), int(ARGS[4]))
    elif len(ARGS) >= 4 and ARGS[1] == 'pick':
        pick(ARGS[2], int(ARGS[3]))
    else:
        make_variants(ARGS[1])
