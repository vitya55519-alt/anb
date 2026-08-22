# Build Changes v3.16.10 — AI-First Photo Generation

## Summary
Fixed Emily (and all characters) serving the same recycled photo. AI generation now ALWAYS takes priority — every user gets fresh unique photos. Community pool and curated library are safety nets for when AI providers fail.

## Changes

### `services/photo_service.py`
- **Removed** community pool priority from `deliver_photo()` — was causing same AI-generated photo to be served to different users.
- **Removed** curated library priority — was causing Emily to always show the same photo.
- **Added** community pool as first fallback in the `except PhotoGenerationError` handler.
- **Delivery priority**: AI generation → community pool fallback → library fallback → error.
- AI-generated photos still enter the community pool (`community_shared=True`) for future fallback use.

### `main.py`
- **Removed** `library_fast` shortcut in `_start_photo_background()` — now always shows "generating..." message and checks budget for free requests.

### `tests/test_v3169_community_pool_static.py`
- **Updated** tests to verify AI-first routing instead of community-pool-first.

## Testing
- 152 tests pass
- L3 deep review: clean

## Impact
- Users now always get fresh AI-generated photos (unique per request).
- No more "same photo, different smile" from recycled community content.
- Community pool and curated library still work as recovery mechanisms when AI providers are down.
