# BUILD CHANGES V3.48.0 — Owner-Photo Character Pack (7 new heroines) + like-badge relocation

## What the owner asked
- Photos 1–3 = ONE character; photos 4, 5, 6, 7, 9, 10 = six more characters.
- Photo 10: sexy AND caring, 36 years old, must communicate age-appropriately.
- Full personas: story, personality, communication manner — everything required.
- Two of the new characters must be caring.
- Photo 8 (screenshot): the like button covers the carousel photo — move it.
- Reference photos: the owner explicitly approved installing their supplied
  photos as-is (ImageGen credits were unavailable; owner confirmed the photos
  are their own AI-generated assets).

## New heroines (ids → look source)
| id | name | age | archetype | caring |
|---|---|---|---|---|
| `violetta_01` | Виолетта | 26 | glamorous chameleon (photos 1–3: brunette canon + 2 extra carousel looks) | – |
| `darina_01` | Дарина | 23 | cozy bookworm caretaker (photo 4) | ✅ |
| `eva_01` | Ева | 24 | easygoing girl next door (photo 5) | – |
| `romina_01` | Ромина | 27 | sensual homemaker, very curvy brunette/blue eyes (photo 6) | – |
| `kristina_01` | Кристина | 25 | nocturnal bold bombshell (photo 7) | – |
| `zlata_01` | Злата | 23 | bratty red-lip teaser, black hair/blue eyes (photo 9) | – |
| `veronika_01` | Вероника | 36 | mature sexy + caring, elegant dark waves (photo 10) | ✅ |

Вероника's persona locks age-appropriate speech: «речь взрослой женщины — без
сленга, без суеты, с паузами», medium/long complete thoughts, flirting with
dignity. Дарина and Вероника are the two caring heroines requested.

## References (`data/references/<folder>/`)
- `_install_v348_refs.py` (one-off, kept for provenance): Pillow-converted the
  owner's photos to PNG (max side 1280) → `00_<name>_canonical_face.png`
  (face-weighted top crop) + `01_<name>_canonical_look.png` (full frame).
- Виолетта additionally got `02_/03_` carousel shots from photos 2–3 — the
  generation anchors are named files (`openai_face_anchor` etc.), so extra
  02_/03_ PNGs only enrich the storefront strip, never identity.

## Registration touchpoints (all seven, mirroring the V3.44.0 precedent)
- `data/characters/<id>.json` ×7 — personality, communication, boundaries,
  full visual_identity (wardrobe pools, preserve_identity, anchors).
- `character_card_service.DEFAULT_CARDS` + `SCENARIO_HOOKS` — auto-seeded to
  DB by `ensure_default_cards()` at startup; hooks are intrigue-only
  (question/tease), never appearance (owner content rule).
- `webapp_service._FACE_REFERENCES` — storefront portraits +
  `builtin_character_ids()` now include the pack.
- `relationship_engine.CHARACTER_PACE` (0.8–1.3) + `PACE_HINTS` (temperament
  injected into every relationship context).
- `retention_features_service` — own voice in ALL nine per-character pools:
  MORNING/EVENING/MISS/JEALOUSY/CLIFFHANGER/GIFT texts + STORY_TEMPLATES +
  MINI_QUESTS + WEEKLY_DATES (no silent fallback to Anna's lines).
- Body geometry: covered by `DEFAULT_FEMALE_BODY_SPEC` (house archetype), same
  as kate/sasha/rex; each DNA also names the bust in `preserve_identity`.

## Mini App: like badge moved off the photo (photo 8 complaint)
- `.charlike` no longer lives inside `.stripwrap` (absolute top-right over the
  strip, covering the 4th thumbnail). It moved into the `.charhero` header row
  (right of the name/age), smaller: `font-size 15px; padding 8px 14px;
  top:10px; right:16px`. `.charhero` is now `position:relative` and the
  title/meta get `padding-right:96px` so long names never slide under it.
- JS untouched — same `#charLike` id, load/toggle handlers work as before.

## Tests
- New `tests/test_v3480_character_pack_static.py` (8 tests): JSON completeness,
  reference files on disk (incl. Виолетта's 02_/03_), card/hook/face-ref/pace
  registration, coverage of all nine retention pools, the two caring personas
  + Вероника's age/voice, and the like-badge relocation.
- `tests/test_v3431_release_static.py`: the pinned `.charlike` CSS literal
  updated to the new hero-row badge (with comment).
- Full suite: **17 failed / 881 passed / 1 error** — exact baseline parity
  (same 17 pre-existing failures + the known test_v392 collection error),
  +8 new green tests. Run with `TELEGRAM_TOKEN` set in the env and
  `--continue-on-collection-errors`.

## Notes for deploy
- No DB schema change — character cards auto-seed; nothing to migrate.
- VERSION file stays at 3.44.4 (tuple-pinned release tests accept it; recent
  releases stopped bumping it).
- All seven heroines ship as `status: active` — the admin panel can flip any
  of them to Premium without a deploy.
