"""V3.122.0 one-off: face, look and back-view references for Айла and Прия.

The owner sent screenshots of real-looking women (Turkish, Indian) as an
ethnicity/style prompt only. Faces here are new: text only, no image is ever
sent to the model, so nobody real gets cloned. The look and the back view are
edits from that new face, so the same girl stays in every shot.

Runs on the owner's PC (the cloud container cannot reach SpicyAPI):
    python _gen_v3122_refs.py <key-file>                 # 2 variants per girl
    python _gen_v3122_refs.py <key-file> round2          # softer faces, v3/v4
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
                  'her wide hips and round toned butt are clearly visible in the tight dress; her face is clearly '
                  'visible in three-quarter profile'),
        dict(face=f'Portrait photo of an {AYLA_FACE}, white off-shoulder blouse, thin gold necklace, cozy pastry shop '
                  'with trays of baklava behind her, warm light, sweet shy smile',
             look='Full look, knees up: white off-shoulder blouse tucked into tight high-waisted blue jeans, '
                  'thin gold necklace, standing in a cozy pastry shop holding a small tray of baklava, warm smile',
             back='Full body from behind: same white off-shoulder blouse and tight high-waisted blue jeans, standing '
                  'at the pastry shop counter with her back to the viewer, glancing back over her shoulder with a '
                  'sweet smile; her wide hips and round toned butt are clearly visible in the tight jeans; her face is '
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
                  'round toned butt are clearly visible; her face is clearly visible in three-quarter profile'),
        dict(face=f'Portrait photo of an {PRIYA_FACE}, emerald-green fitted wrap top, gold jhumka earrings, '
                  'rooftop terrace at sunset with fairy lights, holding a cup of masala chai, warm laugh',
             look='Full look, knees up: emerald-green fitted wrap top and a tight black high-waisted midi skirt, '
                  'gold jhumka earrings, rooftop terrace at sunset with fairy lights, one hand on her hip, '
                  'radiant smile',
             back='Full body from behind: same emerald-green wrap top and tight black high-waisted midi skirt, '
                  'standing at the rooftop railing at sunset with her back to the viewer, looking back over her '
                  'shoulder with a warm laugh; her wide hips and round toned butt are clearly visible in the tight '
                  'skirt; her face is clearly visible in three-quarter profile'),
    ],
}
BODY = {'ayla': AYLA_BODY, 'priya': PRIYA_BODY}
# Round 2: owner wants «попы спортивные круглые» — a toned athletic round butt.
ATHLETIC = ('a very curvy toned hourglass figure with a slim fit waist, wide round hips, toned thighs, a round firm '
            'lifted athletic glute-trained butt (gym-toned bubble butt)')
BODY2 = {'ayla': ATHLETIC + ' and a full natural bust (D cup)', 'priya': ATHLETIC + ' and a large full natural bust (E cup)'}
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


# Round 2 (owner: «фигура да, лица страшные, мягче лица и улыбки не во весь рот»):
# softer, more delicate faces and a gentle closed-lip smile. Same outfits and
# figure as the variants he liked (Айла v2, Прия v1). Saved as v3/v4.
SOFT = (' Soft tender mood: a gentle subtle closed-lip smile, no teeth showing, no wide grin, no laughing, '
        'calm warm eyes looking at the viewer, delicate soft feminine facial features, smooth soft jawline, '
        'soft natural glam makeup, beautiful and sweet.')
AYLA_FACE2 = ('adult Turkish woman, 24 years old, very long voluminous glossy dark chocolate-brown hair in soft '
              'waves, soft almond-shaped warm honey-brown eyes, softly arched groomed dark brows, a delicate oval '
              'face with soft rounded cheeks, a small refined nose, a small beauty mark on her right cheekbone, '
              'soft full caramel-pink lips, light olive skin')
PRIYA_FACE2 = ('adult Indian woman, 23 years old, very long thick glossy jet-black hair, soft large dark brown doe '
               'eyes with a thin line of kajal, softly arched brows, a delicate soft oval face, a small refined '
               'nose with a tiny gold nose stud, a tiny red bindi, soft full rose-berry lips, warm caramel-brown skin')
ROUND2 = {
    'ayla': [
        dict(face=f'Portrait photo of an {AYLA_FACE2}, white off-shoulder blouse, thin gold necklace, cozy pastry '
                  'shop with trays of baklava behind her, warm light',
             look=VARIANTS['ayla'][1]['look'].replace('warm smile', 'gentle closed-lip smile'),
             back=VARIANTS['ayla'][1]['back'].replace('sweet smile', 'soft closed-lip smile')),
        dict(face=f'Selfie portrait of an {AYLA_FACE2}, fitted cream ribbed knit top, small gold hoop earrings, '
                  'sitting by a sunny window of a cozy cafe with a glass of Turkish tea',
             look=VARIANTS['ayla'][1]['look'].replace('warm smile', 'gentle closed-lip smile'),
             back=VARIANTS['ayla'][1]['back'].replace('sweet smile', 'soft closed-lip smile')),
    ],
    'priya': [
        dict(face=f'Portrait photo of an {PRIYA_FACE2}, saffron-orange fitted silk crop blouse, gold jhumka '
                  'earrings, thin gold bangles, bright dance studio with mirrors',
             look=VARIANTS['priya'][0]['look'].replace('mid-dance pose, radiant smile', 'graceful dance pose, gentle closed-lip smile'),
             back=VARIANTS['priya'][0]['back'].replace('radiant smile', 'soft closed-lip smile')),
        dict(face=f'Selfie portrait of an {PRIYA_FACE2}, saffron-orange fitted silk crop blouse, gold jhumka '
                  'earrings, warm evening light by a window with sheer curtains',
             look=VARIANTS['priya'][0]['look'].replace('mid-dance pose, radiant smile', 'graceful dance pose, gentle closed-lip smile'),
             back=VARIANTS['priya'][0]['back'].replace('radiant smile', 'soft closed-lip smile')),
    ],
}


def make_round2() -> None:
    VAR.mkdir(parents=True, exist_ok=True)
    for name, items in ROUND2.items():
        for i, v in enumerate(items, 3):
            face, look, back = (VAR / f'{name}_v{i}_{k}.png' for k in ('face', 'look', 'back'))
            keep = KEEP.format(body=BODY2[name]).replace('dimples, ', '')
            try:
                if not face.exists():  # text only: nobody real gets cloned
                    face.write_bytes(g.render(T2I, v['face'] + '.' + SOFT + QUALITY))
                    print('ok', face.name, flush=True)
                uri = None
                if not look.exists():
                    uri = g.upload(face.read_bytes(), 'image/png')
                    look.write_bytes(g.render(EDIT, keep + v['look'] + '.' + SOFT + QUALITY, [uri]))
                    print('ok', look.name, flush=True)
                if not back.exists():
                    uri = uri or g.upload(face.read_bytes(), 'image/png')
                    back.write_bytes(g.render(EDIT, keep + v['back'] + '.' + SOFT + QUALITY, [uri]))
                    print('ok', back.name, flush=True)
            except Exception as e:
                print('error', name, i, e, flush=True)


def bigger_butt(name: str, n: int) -> None:
    """Owner: «прия вариант 3 но попу больше». Keep the face of v<n>, render the
    look and the back again with a bigger round butt; saved as v<n>b."""
    body = ('a very curvy toned hourglass figure with a slim fit waist, very wide round hips, thick toned thighs, '
            'a big round firm lifted athletic bubble butt (much bigger, fuller and rounder) and a large full natural '
            'bust (E cup)')
    keep = KEEP.format(body=body).replace('dimples, ', '')
    face = VAR / f'{name}_v{n}_face.png'
    uri = g.upload(face.read_bytes(), 'image/png')
    v = ROUND2[name][n - 3]
    for kind in ('look', 'back'):
        out = VAR / f'{name}_v{n}b_{kind}.png'
        if not out.exists():
            out.write_bytes(g.render(EDIT, keep + v[kind].replace('round toned butt', 'big round full bubble butt') + '.' + SOFT + QUALITY, [uri]))
            print('ok', out.name, flush=True)
    shutil.copyfile(face, VAR / f'{name}_v{n}b_face.png')


if __name__ == '__main__':
    if len(ARGS) >= 4 and ARGS[1] == 'bigger':
        bigger_butt(ARGS[2], int(ARGS[3]))
    elif len(ARGS) >= 2 and ARGS[1] == 'round2':
        make_round2()
    elif len(ARGS) >= 4 and ARGS[1] == 'pick':
        pick(ARGS[2], int(ARGS[3]))
    else:
        make_variants()
