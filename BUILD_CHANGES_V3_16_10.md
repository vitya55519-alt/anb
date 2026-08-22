# Build Changes v3.16.10 — AI-First Photo Generation + Character & Underwear Fixes

## Summary
1. AI generation ALWAYS takes priority — no recycled photos from community pool or library.
2. Library fallbacks now use the correct character_id (was hardcoded to Anna → Emily got Anna's photos).
3. Monthly hair color cycle restored for ALL characters (brunette→blonde→chestnut→caramel).
4. Underwear color and style variety — 18 colors × 12 styles randomly picked per photo.

## Changes

### `services/photo_service.py`
- **Removed** community pool and curated library priority from `deliver_photo()`.
- **Added** community pool as first fallback in `except PhotoGenerationError` handler.
- **Fixed** `_deliver_library_failure_fallback`: `CHARACTER_ID` → `character_id` (was always serving Anna's packs).
- **Fixed** `_deliver_library_partial_topup`: added `character_id` parameter, passed to `choose_fallback_pack`.
- **Restored** monthly hair color cycle for ALL characters (was Anna-only since v3.16.8).
- **Added** `UNDERWEAR_COLOR_POOL` (18 colors: black, white, red, pink, beige, brown, green, navy, etc.) and `UNDERWEAR_STYLE_POOL` (12 styles: cotton, microfiber, lace, satin, sports, etc.).
- **Added** `underwear_color` and `underwear_style` fields to `PhotoRequest`; randomly resolved in `_resolve_request`.
- **Updated** `_build_prompt` to inject the specific underwear color and style into the `UNDER-CLOTHING REALISM` line.

### `main.py`
- **Removed** `library_fast` shortcut — always shows "generating..." message.

### `tests/test_v3168_emily_hair_and_video_static.py`
- Updated hair color tests: cycle applies to all characters, not Anna-only.

### `tests/test_v3169_community_pool_static.py`
- Updated delivery priority tests: AI-first routing.
- Added library fallback character_id tests.

## Testing
- 154 tests pass
- L3 deep review: clean

## Root Cause (character bug)
`_deliver_library_failure_fallback` and `_deliver_library_partial_topup` used the `CHARACTER_ID` constant (Anna's ID) instead of the `character_id` parameter. When Emily was selected and AI generation failed, the fallbacks served Anna's library packs.
