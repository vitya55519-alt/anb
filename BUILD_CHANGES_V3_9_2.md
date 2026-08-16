# V3.9.2 — Fast Bulk Photo Library

## Admin import UX
- Relationship levels 1–6 are unchanged.
- Removed the extra import-mode choice from the normal `/libraryimport` flow.
- After character → scene → level, import immediately starts in automatic 3-photo progression mode.
- Upload order is preserved using Telegram `message_id`.
- Every 3 photos become one pack: Base → Stylish → Premium.
- 30 photos become 10 packs automatically.
- One status message is edited at milestones instead of sending many progress messages.
- At 30 photos the importer automatically switches to preview.
- Incomplete 1–2 photo tail is never silently saved as a broken progression pack.

## Existing V3.9.1 libraries
- Added admin command `/libraryregroup <character> <scene> <level>`.
- It converts already-uploaded one-photo collection packs into 3-photo progression packs using existing Telegram `file_id`s; no re-upload is required.
- A remainder of 1–2 photos is left untouched.
- Seen-history is migrated to the new packs.

Examples:
- `/libraryregroup anna_01 selfie 1`
- `/libraryregroup anna_01 selfie 2`
