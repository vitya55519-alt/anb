# V3.51.3 — POV dates rolled back + sensual private expressions + photo-pool reuse

## Owner request
> «фото свидания от первого лица — какая-то вообще херня. Давай вернем всё
> обратно, как они были» … «сексуальные — всё отлично, только сделай какие-то
> эмоции … язык поднимается» … «скопилось их 20 штук — зачем генерировать новые,
> если можно отправить готовую фото для определенной модели».

Locked decisions (owner): (1) **roll back** the V3.51.2 first-person POV date
photos — keep the studio NSFW leg (that part «всё отлично»); (2) give the
«наедине»/adult photos **sensual facial expressions** (tongue grazing the lip,
bitten lip, smouldering bedroom eyes), private scenes only; (3) **photo-pool
reuse** — still generate to build a stockpile, but when enough ready shots exist
for a scene, send a random one instead of paying the provider again.

## 1. POV date photos rolled back (`services/dates_service.py` + `main.py`)
- `DATE_POV_ANGLE` removed from `dates_service.py`; the module is back to the
  plain `@dataclass(frozen=True) Date`.
- `_webapp_media_scene` reverted to its original 3-arg signature
  (`telegram_id, character_id, scene`) — no `angle` threading.
- Both date reward paths shoot the plain scene framing again: Mini App
  `_webapp_media_scene(telegram_id, character_id, date.scene)` and bot
  `_deliver_date_reward` → `PhotoRequest(scene=date.scene, mood='romantic')`.
- The V3.51.2 uncensored studio leg (`picture_final_prompt(adult=)`, adult route
  to `generate_private_photo_t2i`) is **kept untouched** — the owner liked it.

## 2. Sensual expressions on EVERY photo (`services/photo_expression_service.py` + `photo_service.py`)
- Six new desirous faces in `EXPRESSIONS`: `desire` (tongue tip grazing the lower
  lip, heavy-lidded), `biting_lip`, `bedroom_eyes` (smouldering half-closed gaze,
  parted lips), `blow_kiss`, `licking_lips` (tongue running up over the lip — the
  owner's «язык поднимается»), `pouty_seductive`.
- `SENSUAL_KEYS` (8 keys, kept wide for variety) + `shuffled_sensual_variety_keys()`
  define the per-frame rotation.
- `_resolve_request` now walks the **sensual** pool as the DEFAULT per-frame
  rotation on **every** scene — the owner asked for sensual emotion across all
  photos, not just the private ones («чувственные эмоции должны быть на всех фото
  разнообразны»). The earlier private-only branch was dropped; `shuffled_variety_keys()`
  is no longer called from the resolver. An explicit chat-mood `expression_key`
  still overrides the rotation (so a comfort/sympathy shot is not seductive).

## 3. Photo-pool reuse (`services/private_photo_service.py` + `main.py`)
- `PRIVATE_POOL_MIN = 10` — the stockpile threshold (raise it, or set it very
  high, to effectively disable reuse).
- `pool_get(character_id, category, type_id, min_count)`: reads the **shared
  cache rows only** (`user_id == 0`), matched on the stable `category` +
  `type_id` columns; if the pool holds at least `min_count` shots it returns a
  `random.choice` of them, otherwise `None` (→ generate). The volatile full
  prompt hash carries the per-frame expression/pose rotation and almost never
  repeats, which is why exact `cache_get` rarely hits — this reuses the pool that
  actually accumulates.
- `_webapp_media_hot`: after the exact `cache_get` miss and **before** any
  provider call, `pool_get` is tried; a hit is charged like any send
  (`spend_peaches`), saved into the user's gallery (`gallery_save`), achievements
  run, and returned — skipping the render. Generation still fills the pool.

## Tests
- Updated pins for the widened rotation: `test_v3317_photo_variety` (the resolver
  now calls `shuffled_sensual_variety_keys()` instead of `shuffled_variety_keys()`).
- New: `tests/test_v3513_sensual_pool_static.py` (4 tests — the sensual keys
  defined + tongue/pout notes present + `SENSUAL_KEYS`/`shuffled_sensual_variety_keys`,
  the sensual rotation applied to ALL scenes with no tasteful branch and the
  expression_key override, `pool_get` signature/threshold/user_id==0/random.choice/
  short-pool→None, and `_webapp_media_hot` wiring pool_get after cache miss before
  generation with charge + gallery_save).
- `tests/test_v3512_date_pov_studio_nsfw_static.py` → renamed
  `tests/test_v3512_studio_nsfw_static.py`, rewritten to 3 tests: a POV-revert
  guard (`DATE_POV_ANGLE` gone from dates_service + main, original
  `_webapp_media_scene` signature, `PhotoRequest(scene=date.scene, mood='romantic')`)
  plus the two kept studio-leg pins.
- Reverted pins for the rolled-back signatures: `test_v3410`, `test_v34417`,
  `test_v317_apartment_gifts_dates`, `test_v3437`.
- Full suite: 17 failed / 940 passed / 1 error — exact baseline parity (the 17 +
  error are pre-existing and unrelated: bust-consistency, video-kind, feature-menu,
  chat-media scene gating, `_seedream_t2i` signature, bulk library).

## Deploy notes
- No schema change — `pool_get` only reads existing `PrivateGallery` columns
  (`user_id`, `character_id`, `category`, `type_id`, `image_bytes`).
- Location/mood/lingerie-colour nuance is **not** matched by the pool; a reused
  shot is same character + scene + pose only. Acceptable trade-off to cut provider
  spend; tune `PRIVATE_POOL_MIN` if variety must stay higher.
- Reuse only applies to the «Наедине»/`_webapp_media_hot` flow; free progression
  and the public photo menu are unchanged.
- `VERSION` not bumped (3.5x line).
