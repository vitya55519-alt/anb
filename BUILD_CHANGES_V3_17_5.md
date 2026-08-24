# BUILD CHANGES v3.17.5

## At-home lingerie sets at relationship levels 5-6

- New `HOME_LINGERIE_SCENES = {'selfie', 'home', 'mirror'}` in
  `services/photo_service.py`.
- `_build_prompt`: on the Seedream route at level 5+, at-home scenes switch to
  a lingerie-only look — the wardrobe becomes "only her {color} lingerie
  {style} set — matching bra and panties worn as the entire outfit in the
  privacy of her home, no outerwear at all", the under-clothing rule is
  replaced by "her lingerie IS the outfit", and a `HOME LINGERIE LOOK` framing
  line is added. The color/style of the set still rotates per set.
- All other ordinary scenes at level 5-6 get a more daring wardrobe:
  ", styled with a daring, revealing cut that shows more skin while staying a
  real outfit" (Seedream route only; private-tier scenes keep their own
  framing).
- The general-audience OpenAI fallback route is untouched (no lingerie-only
  or revealing-cut overrides) to stay within its moderation envelope.
- Bust identity unchanged and pinned: Russian size 5 (E cup) in all six
  identity blocks and `data/characters/anna.json`.

## Community pool protection

High-level at-home lingerie sets must neither leak to other users nor be
diluted by low-level clothed pool photos:

- `deliver_photo` computes `home_lingerie_mode` (scene in HOME_LINGERIE_SCENES
  and relationship level >= 5).
- Pool-first serving is skipped for such requests (`and not
  home_lingerie_mode`), so a level 5-6 user never receives someone else's
  clothed selfie/home/mirror photos.
- `_send_frame` now stores `community_shared=not home_lingerie_mode`, so these
  frames never enter the shared pool.

## Tests

- New `tests/test_v3175_home_lingerie_static.py` (8 tests): constant, prompt
  override, revealing cut, pool protection, bust pin, and three runtime
  `_build_prompt` checks (level 6 home = lingerie-only, level 4 home stays
  clothed, level 5 park = revealing cut on Seedream but not on the OpenAI
  route).
- Updated pins in `test_v3169_community_pool_static.py`,
  `test_v3174_community_pool_first_static.py` (`community_shared=not
  home_lingerie_mode`) and `test_v31611_underwear_underlay_static.py`
  (`if` → `elif` after the home-lingerie branch).
