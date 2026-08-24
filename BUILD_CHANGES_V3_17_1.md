# Build Changes — v3.17.1

## Anna bust size up + visible-underwear system

### `services/photo_service.py`
- **Bust**: Anna's canonical bust bumped from Russian size 4 (D cup) to
  **Russian size 5 (E cup)** across all identity blocks:
  `BUST_CONSISTENCY_RULE`, `ANNA_BODY_IDENTITY`, `OPENAI_REFERENCE_PROTOCOL`,
  `ORDINARY_BODY_IDENTITY`, `BODY_REINFORCEMENT`, `SEEDREAM_IDENTITY_LOCK`.
- **Added** `UNDERWEAR_VISIBILITY_DETAILS` pool (strap on shoulder, waistband
  above jeans, unbuttoned shirt, lace edge at neckline, sheer fabric, lower
  neckline) — one random detail injected into the `UNDER-CLOTHING REALISM`
  line per set so the lingerie reads believably and varies shot to shot.
- **Added** `PRIVATE_SCENE_TIERS` for `lingerie` / `personal` /
  `private_fashion` with `standard` / `suggestive` / `revealing` framings;
  `_build_prompt` picks the tier by relationship level (≥6 revealing, ≥5
  suggestive, else standard) and adds a `PRIVATE SCENE FRAMING` line.
- **Added** new scenes `peek` (lingerie peeks from under the everyday outfit)
  and `dressing` (underwear visible while getting dressed), both level 4,
  wired into `SCENES`, `SCENE_LEVELS`, `SCENE_GROUP` (home wardrobe), and
  `AUTO_CAPTIONS`. They stay ordinary scenes — private routing sets are
  unchanged.
- **Fixed** a latent `_build_prompt` bug: the `if request.hair_color else ''`
  condition was parsed as applying to the whole concatenated prompt (operator
  precedence), so any request without `hair_color` returned an empty prompt.
  The hair line is now parenthesized.

### `data/characters/anna.json`
- `preserve_identity` bust trait updated to size 5 (E cup).

### Tests
- `test_v3156_anna_bust_identity_static.py`, `test_v3141_photo_pipeline_hardening.py`:
  re-pinned to size 5 / E cup.
- `tests/test_v3171_underwear_visibility_static.py` (new): visibility pool +
  injection, private tier mapping, new scenes, bust bump.

### `VERSION`
- Bumped to `3.17.1`.
