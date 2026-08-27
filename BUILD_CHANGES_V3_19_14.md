# BUILD CHANGES V3.19.14 — community gallery moderation for the owner

Owner asked whether all generated photos go into the shared gallery, and
requested a way to see that gallery and remove bad photos.

## Answers

- Yes: every AI-generated **public** frame enters the community pool
  (`community_shared=True`) and can be served to other users; intimate
  scenes and at-home lingerie sets stay private. Paid credit sets always
  generate fresh AI photos and are unaffected.

## Changes

- `services/photo_service.py`: new admin helpers — `admin_pool_count`,
  `admin_pool_get`, `admin_pool_latest_id`, `admin_pool_neighbor`,
  `admin_pool_set_shared`. All operate only on community-shared deliveries.
- `main.py`:
  - Admin panel gains a «🖼 Общая галерея (модерация)» button.
  - New `poolmod:` callback flow: browse the pool newest-first (photo swaps
    in place via `edit_media`, caption shows id/scene/character/provider/
    date/pool size), «❌ Убрать из галереи» excludes the frame, «⬅️ Новее»
    and «➡️ Старше» navigate. Admin-only (gated by `ADMIN_TELEGRAM_IDS`).
  - Removal only flips `community_shared` to False — the original owner
    keeps the photo in their own history; it is simply never served to
    other users. Tracked as `admin_pool_remove`.
- `tests/test_v31914_pool_moderation_static.py`: pins helpers, admin gate,
  flag-flip removal (no row delete) and in-place navigation.
