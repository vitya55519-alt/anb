# V3.9.3 — Safe Library + Gym

- Added 🏋️ Gym scene to the user photo menu and admin photo-library importer (relationship level 2+).
- Added gym-specific scene prompt, captions, wardrobe progression and shot variants.
- Library importer now respects each scene's minimum relationship level.
- Added automatic multimodal moderation for uploaded library images before saving Telegram file_ids.
- Images flagged in sexual categories are rejected and never enter the pre-generated library.
- Moderation failures fail closed: unverified images are not saved.
- Moderation endpoint is configurable with LIBRARY_MODERATION_ENABLED and LIBRARY_MODERATION_MODEL.
