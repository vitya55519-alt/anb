"""V3.79.0 round 2: owner found Милана, Полина, Даша, Камила, Рита «страшные»,
not like his photos, and wants them sexier. Two glam variants each (new
faces, text only), saved to data/references/_new6_variants/ for his pick.
    python _gen_v379_variants.py <file-with-SPICYAPI_KEY> [girl ...]
"""
import pathlib
import sys

import _gen_v379_refs as g

ROOT = pathlib.Path(__file__).resolve().parent
ONLY = set(sys.argv[2:])
OUT = ROOT / 'data' / 'references' / '_new6_variants'

GLAM = (' Glamorous Instagram influencer photo, flawless smooth glowing skin with a soft beauty retouch, '
        'full glam makeup, long fluffy lashes, plump glossy lips, very attractive model face, '
        'sultry seductive expression, sharp focus on the eyes, warm flattering light, '
        'original fictional woman with a unique face, not a celebrity, '
        'anatomically correct: exactly two arms and two hands, five fingers on each hand. '
        'Adult woman, one person only, fully dressed, no nudity, no text, no watermark, no logo.')
SEXY = (' Sensual glamour mood: confident seductive body language, half-lidded eyes, eye contact with the viewer, '
        'tight body-hugging outfit that shows off her curves and deep cleavage.')

GIRLS = {
    'milana': dict(
        faces=['Selfie portrait of a stunning adult woman, 26 years old, very long sleek straight chestnut-brown hair, '
               'big bright ice-blue almond eyes, sharp arched brows, sculpted cheekbones, small refined nose, very full '
               'pouty nude lips, wearing a tight beige ribbed turtleneck that hugs a huge bust, cozy restaurant with '
               'bokeh lights behind, cool seductive gaze',
               'Portrait of a gorgeous adult woman, 26 years old, very long glossy straight brown hair with a side part, '
               'large striking blue doe eyes, thick dark arched brows, soft heart-shaped face, small upturned nose, '
               'big plump glossy lips, tight cream ribbed turtleneck stretched over a very large bust, evening café '
               'window behind, sultry calm look'],
        look='Full look, knees up: tight beige ribbed turtleneck sweater dress hugging her huge bust, narrow waist and '
             'wide hips, standing by the bar of an evening restaurant, one hand on her hip, inviting half-smile',
        body='a very voluptuous hourglass figure with a huge round bust (F cup), a tiny waist and wide hips'),
    'polina': dict(
        faces=['Portrait of a stunning adult woman, 22 years old, long voluminous wavy golden blonde hair, deep golden '
               'tan, big hazel-green eyes with smoky bronze makeup, full glossy pink-nude lips, soft sculpted face, '
               'cream ribbed camisole with a low neckline, sitting on a white bed in a bright bedroom, sultry pout',
               'Selfie of a gorgeous adult woman, 22 years old, long tousled honey-blonde beach waves, glowing tanned '
               'skin, light brown cat eyes with winged liner, high cheekbones, very full glossy lips, thin-strap cream '
               'camisole, messy white sheets, soft morning light, seductive sleepy look'],
        look='Full look, knees up: tight cream ribbed camisole with a low neckline and tiny cream lounge shorts, '
             'sitting on a messy white bed leaning back on her hands, legs crossed, sultry look at the viewer',
        body='a tanned curvy hourglass figure with a full round bust (D cup), narrow waist and round hips'),
    'dasha': dict(
        faces=['Portrait of a stunning adult woman, 25 years old, dark brown hair in a loose sexy messy bun with long '
               'face-framing strands and curtain bangs, a few faint freckles on the nose, warm amber-brown eyes with '
               'soft smoky makeup, full plump nude lips, soft sculpted face, thin gold necklace, black ribbed tank top '
               'with a deep scoop neckline over a very full bust, dim bedroom, calm sultry gaze',
               'Selfie of a gorgeous adult woman, 25 years old, long dark chocolate hair half up with wispy curtain '
               'bangs, light freckles on the cheeks, big brown doe eyes with long lashes, small nose, very full glossy '
               'lips, black tank top with a low neckline showing deep cleavage, dim moody room, mysterious seductive look'],
        look='Full look, knees up: tight black ribbed tank top with a deep neckline and tight grey leggings, sitting on '
             'the edge of a bed in a dim evening bedroom, leaning forward slightly, sultry teasing look',
        body='a curvy hourglass figure with a very full round bust (E cup), narrow waist and wide hips'),
    'kamila': dict(
        faces=['Car selfie of a stunning adult woman, 22 years old, very long sleek straight jet-black hair, honey-brown '
               'almond eyes with glam makeup and long lashes, soft groomed brows, smooth light olive skin, small refined '
               'nose, very full glossy pink lips in a flirty kiss pout, gold coin pendant, black tank top with white '
               'lace bra edge showing deep cleavage, seatbelt on, pink sunset desert highway through the window',
               'Selfie of a gorgeous adult woman, 22 years old, very long glossy straight black hair with a middle part, '
               'big light-brown doe eyes, softly arched brows, delicate oval face, small nose, big plump glossy lips, '
               'gold necklace, tight black tank top over a large bust, sitting in a car at pink sunset, sultry look'],
        look='Full look, knees up: tight black tank top with a white lace bra edge showing deep cleavage and a short '
             'denim mini skirt, leaning against the side of a black car on a roadside at pink sunset, sultry pose',
        body='a curvy hourglass figure with a large round bust (E cup), a tiny waist and wide round hips'),
    'rita': dict(
        faces=['Portrait of a stunning adult woman, 24 years old, long voluminous wavy copper-red hair, porcelain skin '
               'with a few faint freckles, big bright green almond eyes with smoky makeup and long lashes, sculpted '
               'cheekbones, small nose, very full glossy nude lips slightly parted, small gold hoops, tight charcoal '
               'turtleneck over a full bust, light grey studio background, seductive soft smile',
               'Portrait of a gorgeous adult woman, 24 years old, shoulder-length glossy ginger-red hair with soft waves, '
               'smooth fair skin, light freckles on the nose, green cat eyes with winged liner, soft arched brows, plump '
               'glossy lips, tight dark grey fitted top, plain grey background, flirty half-smile looking at the viewer'],
        look='Full look, knees up: tight charcoal-grey turtleneck, short plaid mini skirt and black stockings, sitting '
             'on the edge of a desk in a sunny apartment, legs crossed, flirty seductive look at the viewer',
        body='a slender curvy hourglass figure with a full round bust (D cup) and round hips'),
}

if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    for name, d in GIRLS.items():
        if ONLY and name not in ONLY:
            continue
        for i, face in enumerate(d['faces'], 1):
            fp = OUT / f'{name}_v{i}_face.png'
            lp = OUT / f'{name}_v{i}_look.png'
            try:
                if not fp.exists():
                    fp.write_bytes(g.render('bytedance/seedream-5.0-pro/text-to-image', face + '.' + GLAM))
                    print('ok', fp)
                if not lp.exists():
                    uri = g.upload(fp.read_bytes(), 'image/png')
                    prompt = ('The same woman as in the reference image: keep her exact face, eyes, nose, lips, hair '
                              f'color and length, skin tone. Her figure: {d["body"]}. {d["look"]}.' + SEXY + GLAM)
                    lp.write_bytes(g.render('bytedance/seedream-5.0-pro/edit', prompt, [uri]))
                    print('ok', lp)
            except Exception as e:  # keep going
                print('error', name, i, e)
