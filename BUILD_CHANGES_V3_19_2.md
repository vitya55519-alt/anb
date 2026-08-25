# BUILD CHANGES V3.19.2 — Fully-Clothed Public Scenes + Seedream Fallback

## 1. Public scenes stay fully clothed (owner policy)
- At relationship levels 5-6 the character no longer shows lingerie in public
  venue scenes: restaurant, car, gym, cinema, fashion, embankment, evening,
  bar, karaoke, rooftop, club.
- `_build_prompt`: the underwear color/style is now named only in the
  dedicated private scenes (`personal`, `lingerie`, `private_fashion`). The
  old `level_key >= 5` gate made the model draw visible lingerie under
  everyday outfits in restaurants/bars/cars — removed.
- The level-5+ "daring, revealing cut" wardrobe escalation for ordinary
  scenes is removed.
- `LEVEL_VISUAL_RULES` / `OPENAI_LEVEL_VISUAL_RULES` level 5-6 no longer
  allow "visible lace details".
- `LEVEL_UNDERLAY_RULES` levels 5-6 now keep the lingerie completely hidden
  in public scenes (with an explicit carve-out for dedicated lingerie scenes).
- Intimate looks stay where the owner wants them: at-home selfie/home/mirror
  lingerie sets at level 5+ (`HOME_LINGERIE_SCENES`, unchanged) and the
  private scenes.

## 2. Retired 'peek' and 'dressing' scenes
- Removed from `SCENE_LEVELS`, so `scene_allowed_for_stage` rejects them and
  no menu/generation can route to them anymore. Definitions remain in
  `SCENES`/`AUTO_CAPTIONS`/`_PRIVATE_LIBRARY_SCENES` for old library photos.

## 3. Seedream HTTP 422 no longer kills the photo
- `_run_routed_photo_set`: when the Seedream set fails (e.g. content-policy
  HTTP 422, "seedream45"), the request now falls back through
  Gemini Image → OpenAI → Pollinations before surfacing an error.

## Tests
- New `tests/test_v3192_dressed_public_scenes_static.py` (6 tests).
- Updated pins: `test_v3175_home_lingerie_static.py`,
  `test_v31611_underwear_underlay_static.py`,
  `test_v3171_underwear_visibility_static.py`,
  `test_v3163_welcome_voice_levels_static.py`.
