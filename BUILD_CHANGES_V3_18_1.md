# BUILD CHANGES v3.18.1

## Intimate photo tier (level 6) and sensual video animation

Adds two new adult photo scenes — **nude** and **tease** — unlocked at
relationship level 6 (committed), plus a sensual animation prompt for video
generation on adult/intimate photo scenes.

### New scenes
- `services/photo_service.py`: `ADULT_SCENES = {'nude', 'tease'}`.
  - `SCENES`: `'nude'` = tasteful artistic nude portrait; `'tease'` = playful
    sensual photo from behind.
  - `SCENE_LEVELS`: both gated at level 6.
  - `SCENE_GROUP`: both → `'adult'`.
  - `AUTO_CAPTIONS`, `SHOT_VARIANTS`, `PRIVATE_SCENE_TIERS`: entries for both.
  - `ADULT_SAFETY` constant: an adult safety string that explicitly permits
    artistic nudity, overriding the default Seedream "No nudity" lock for these
    scenes only.

### Access control
- `is_custom_request` and `requires_adult_confirmation` now include `nude` and
  `tease`: they require 18+ confirmation and go through the paid custom-photo
  path (Stars), same as `lingerie` and `private_fashion`.
- `parse_photo_request`: explicit text like «голая» / «nude» now maps to
  `scene='nude'` (or `scene='tease'` when rear-view keywords are present)
  instead of being blocked to a safe `fashion` scene. The level gate and age
  gate protect access for users who are not level 6 or not adult-confirmed.

### Seedream integration
- `_seedream_request` gains `allow_adult: bool = False` keyword parameter.
  When `True`, `enable_safety_checker` is set to `False`, disabling the fal.ai
  content-safety filter for that request only.
- `_run_seedream_set` passes `allow_adult = request.scene in ADULT_SCENES` to
  the initial request; the safe-retry path always keeps the safety checker on.
- `_build_prompt`: adult scenes override wardrobe to
  `nothing — artistic nude, no clothing at all`, clear the under-clothing
  rule, and swap the safety string to `ADULT_SAFETY`.
- `_seedream_safe_retry_request`: nude/tease scenes retry with opaque lingerie
  (never nude), same as personal/lingerie.

### Community pool protection
- Adult scenes are added to `_PRIVATE_LIBRARY_SCENES` (never served from pool).
- `community_shared` flag in `deliver_photo` now also excludes `ADULT_SCENES`,
  so AI-generated nude photos are never shared back into the community pool.

### Sensual video animation
- `services/cloud_video_service.py`: new `SENSUAL_ANIMATION_PROMPT` — slow
  sensual movement (hand through hair, trailing along waist and hip, teasing
  smile), no explicit-action ban (the source image itself may be nude for adult
  scenes), no wardrobe change, no body transformation.
- `main.py` `_run_video_background`: selects `SENSUAL_ANIMATION_PROMPT` when
  `delivery['scene']` is in the adult/intimate set (`nude`, `tease`,
  `personal`, `lingerie`, `private_fashion`) and passes `prompt=anim_prompt`
  to all video engines (Gemini, Replicate, fal, HF — all already accept the
  `prompt` kwarg). Non-intimate scenes pass `None`, preserving the existing
  default `ANIMATION_PROMPT` behavior.

### Menu
- `main.py` `PHOTO_LABELS`: `'nude': '🔥 Обнажённая'`, `'tease': '🍑 Дразнит'`.
- `PHOTO_MENU_ORDER`: both appended. They surface automatically at level 6
  via the existing `SCENE_LEVELS` gate in `photo_keyboard`.

## Tests
- New `tests/test_v3181_intimate_tier_static.py`: 25+ tests covering scene
  registries, access control, parse_photo_request mapping, _build_prompt adult
  branch, _seedream_request allow_adult, provider routing, pool protection,
  and sensual animation prompt wiring.
