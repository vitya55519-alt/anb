# V3.26.0 — video preset refresh: close-up motion replaces hug/dance

## Owner report

«видео ужасное, предложи свои варианты, вместо кнопок, кроме поцелуя» — the
hug/dance presets rendered poorly: full-body choreography from a single still
frame is exactly what i2v engines distort the most (arms, limb blending,
identity drift). The owner asked for new button presets, keeping only kiss.

## 1. New preset set in `services/cloud_video_service.py`

Retired: `hug` (Обнимашки), `dance` (Танец). Kept: `kiss`. Added five
low-amplitude, close-up motions that i2v engines render cleanly:

- 😏 `wink` Подмигивание — playful wink, teasing smile, tucks a hair strand
  behind her ear.
- 💨 `turn` Оборот — slow turn toward the camera, hair flows and settles.
- 🤫 `whisper` Шёпот — POV: leans to the viewer's «eyes», whispers a secret.
- 🖐 `touch` Прикосновение — POV: slowly reaches a hand toward the camera.
- 🔥 `caress` Ласка — sensual: her hand trails along her side and rests above
  her heart, head tilt, half-closed eyes. Deliberately keeps the
  «no sexual action» line so Veo/WAN moderation accepts it.

Every prompt keeps the v3.19 identity locks: 'Animate this exact photo',
'Preserve her identity', 'No wardrobe change', 'no extra people', breathing
and blink micro-motion.

## 2. Generic preset keyboard in `main.py`

`_video_preset_keyboard` no longer hardcodes keys — it builds rows from
`VIDEO_PRESETS` two-per-row and appends ✨ Авто. Adding or removing presets
now never requires keyboard changes.

## 3. Tests

`tests/test_v3260_video_presets_closeup_static.py` — 6 tests. Old pins in
test_v319, test_v31912, test_v3240 updated to the new preset set.

## Owner notes

- «сжимать грудь» в явном виде ставить нельзя: видео-движки (Veo/WAN)
  отклоняют откровенно сексуальные действия, либо дают артефакты рук.
  «Ласка» — максимум, который проходит модерацию движка и выглядит чисто:
  рука скользит по телу и ложится на грудь.
- Авто-режим не тронут: для интимных сцен он по-прежнему берёт
  SENSUAL_ANIMATION_PROMPT.
