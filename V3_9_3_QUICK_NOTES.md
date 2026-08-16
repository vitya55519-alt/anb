# V3.9.3 quick notes

## Library upload safety
- Pre-generated library uploads are checked with `omni-moderation-latest` before their Telegram `file_id` is persisted.
- Photos flagged in sexual categories are rejected from the library.
- Moderation errors fail closed: unverified images are not saved.
- `LIBRARY_MODERATION_ENABLED=true` by default.
- The importer only shows relationship levels allowed by the scene's minimum level.

## Gym
- New scene key: `gym`
- Label: `🏋️ Зал`
- Unlock: relationship level 2
- Added gym prompt, captions, athletic wardrobe pools, shot progression and natural-language intent parsing.
