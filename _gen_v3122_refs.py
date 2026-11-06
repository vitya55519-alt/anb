"""V3.122.0 one-off: face, look and back-view references for Айла and Прия.

The owner sent screenshots of real-looking women (Turkish, Indian) as an
ethnicity/style prompt only. Faces here are new: text only, no image is ever
sent to the model, so nobody real gets cloned. The look and the back view are
edits from that new face, so the same girl stays in every shot.

Runs on the owner's PC (the cloud container cannot reach SpicyAPI):
    python _gen_v3122_refs.py <key-file>                 # 2 variants per girl
    python _gen_v3122_refs.py <key-file> pick ayla 2     # v2 -> canonical refs
Variants go to %USERPROFILE%/Desktop/new_girls_preview_v3122, not to the repo.
"""
import pathlib
import shutil
import sys

ARGS = sys.argv[1:]
sys.argv = sys.argv[:2]  # _gen_v379_refs reads the key from argv[1], filters by argv[2:]
import _gen_v379_refs as g  # noqa: E402

VAR = pathlib.Path.home() / 'Desktop' / 'new_girls_preview_v3122'
T2I = 'bytedance/seedream-5.0-pro/text-to-image'
EDIT = 'bytedance/seedream-5.0-pro/edit'
QUALITY = (' High-end glamour smartphone photo, flawless smooth glam skin, sharp focus on the eyes, '
           'original fictional woman with a unique face, not a celebrity, not an actress, '
           'anatomically correct: exactly two arms and two hands, five fingers on each hand. '
           'Adult woman, mature grown-up features, one person only, fully dressed, no nudity, no text, '
           'no watermark, no logo.')
WARM = ' Warm friendly mood: a big genuine happy smile, eye contact with the viewer, inviting and sweet.'

AYLA_FACE = ('adult Turkish woman, 24 years old, very long voluminous glossy dark chocolate-brown hair in big soft '
             'waves, warm honey-brown eyes with soft brown smoky makeup, thick dark brows, a slightly round face '
             'with soft cheeks and deep dimples when she smiles, a small beauty mark on her right cheekbone, '
             'full glossy caramel-pink lips, light olive skin')
AYLA_BODY = ('a very curvy hourglass figure with a slim waist, very wide round hips, thick thighs, a big round full '
             'lifted butt and a full natural bust (D cup)')
PRIYA_FACE = ('adult Indian woman, 23 years old, very long thick glossy jet-black hair, large dark brown eyes lined '
              'with black kajal, thick arched brows, a heart-shaped face, a tiny gold nose stud, a small red bindi, '
              'full glossy berry lips, a wide bright smile with white teeth, warm caramel-brown skin')
PRIYA_BODY = ('a very curvy hourglass figure with a narrow waist, very wide round hips, thick thighs, a big round '
              'full butt and a large full natural bust (E cup)')

VARIANTS = {
    'ayla': [
        dict(face=f'Selfie portrait of an {AYLA_FACE}, fitted cream ribbed knit top, small gold hoop earrings, '
                  'sitting at a seaside cafe in Istanbul with a glass of Turkish tea, ferries and the sea behind her, '
                  'laughing',
             look='Full look, knees up: fitted cream ribbed knit midi dress hugging her hips, small gold hoops, '
                  'standing on a sunny seaside promenade with the sea behind her, one hand in her hair, big smile',
             back='Full body from behind: same fitted cream ribbed knit midi dress, she walks away along the sunny '
                  'seaside promenade and looks back over her shoulder at the viewer with a big playful smile; '
                  'her wide hips and big round butt are clearly visible in the tight dress; her face is clearly '
                  'visible in three-quarter profile'),
        dict(face=f'Portrait photo of an {AYLA_FACE}, white off-shoulder blouse, thin gold necklace, cozy pastry shop '
                  'with trays of baklava behind her, warm light, sweet shy smile',
             look='Full look, knees up: white off-shoulder blouse tucked into tight high-waisted blue jeans, '
                  'thin gold necklace, standing in a cozy pastry shop holding a small tray of baklava, warm smile',
             back='Full body from behind: same white off-shoulder blouse and tight high-waisted blue jeans, standing '
                  'at the pastry shop counter with her back to the viewer, glancing back over her shoulder with a '
                  'sweet smile; her wide hips and big round butt are clearly visible in the tight jeans; her face is '
                  'clearly visible in three-quarter profile'),
    ],
    'priya': [
        dict(face=f'Selfie portrait of an {PRIYA_FACE}, saffron-orange fitted silk crop blouse with short sleeves, '
                  'gold jhumka earrings, thin gold bangles, bright dance studio with mirrors, joyful laugh',
             look='Full look, knees up: saffron-orange fitted silk crop blouse and a matching high-waisted long '
                  'flowing lehenga skirt with gold border sitting low on her wide hips, bare toned midriff, gold '
                  'jhumka earrings and bangles, dance studio with mirrors, mid-dance pose, radiant smile',
             back='Full body from behind: same saffron-orange crop blouse and high-waisted lehenga skirt hugging her '
                  'wide hips, long jet-black hair in a thick braid down her back, standing in the dance studio with '
                  'her back to the viewer and looking back over her shoulder with a radiant smile; her wide hips and '
                  'big round butt are clearly visible; her face is clearly visible in three-quarter profile'),
        dict(face=f'Portrait photo of an {PRIYA_FACE}, emerald-green fitted wrap top, gold jhumka earrings, '
                  'rooftop terrace at sunset with fairy lights, holding a cup of masala chai, warm laugh',
             look='Full look, knees up: emerald-green fitted wrap top and a tight black high-waisted midi skirt, '
                  'gold jhumka earrings, rooftop terrace at sunset with fairy lights, one hand on her hip, '
                  'radiant smile',
             back='Full body from behind: same emerald-green wrap top and tight black high-waisted midi skirt, '
                  'standing at the rooftop railing at sunset with her back to the viewer, looking back over her '
                  'shoulder with a warm laugh; her wide hips and big round butt are clearly visible in the tight '
                  'skirt; her face is clearly visible in three-quarter profile'),
    ],
}
BODY = {'ayla': AYLA_BODY, 'priya': PRIYA_BODY}
KEEP = ('The same woman as in the reference image: keep her exact face, eyes, nose, lips, dimples, '
        'hair color and length, skin tone. Her figure: {body}. ')


def make_variants() -> None:
    VAR.mkdir(parents=True, exist_ok=True)
    for name, items in VARIANTS.items():
        for i, v in enumerate(items, 1):
            face = VAR / f'{name}_v{i}_face.png'
            look = VAR / f'{name}_v{i}_look.png'
            back = VAR / f'{name}_v{i}_back.png'
            keep = KEEP.format(body=BODY[name])
            try:
                if not face.exists():  # text only: nobody real gets cloned
                    face.write_bytes(g.render(T2I, v['face'] + '.' + WARM + QUALITY))
                    print('ok', face.name, flush=True)
                uri = None
                if not look.exists():
                    uri = g.upload(face.read_bytes(), 'image/png')
                    look.write_bytes(g.render(EDIT, keep + v['look'] + '.' + WARM + QUALITY, [uri]))
                    print('ok', look.name, flush=True)
                if not back.exists():
                    uri = uri or g.upload(face.read_bytes(), 'image/png')
                    back.write_bytes(g.render(EDIT, keep + v['back'] + '.' + QUALITY, [uri]))
                    print('ok', back.name, flush=True)
            except Exception as e:  # keep going with the other variants
                print('error', name, i, e, flush=True)


def pick(name: str, n: int) -> None:
    out = g.ROOT / 'data' / 'references' / name
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(VAR / f'{name}_v{n}_face.png', out / f'00_{name}_canonical_face.png')
    shutil.copyfile(VAR / f'{name}_v{n}_look.png', out / f'01_{name}_canonical_look.png')
    shutil.copyfile(VAR / f'{name}_v{n}_back.png', out / f'02_{name}_canonical_back.png')
    print('picked', name, n)


if __name__ == '__main__':
    if len(ARGS) >= 4 and ARGS[1] == 'pick':
        pick(ARGS[2], int(ARGS[3]))
    else:
        make_variants()
