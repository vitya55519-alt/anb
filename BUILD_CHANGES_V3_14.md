# AnnaBot V3.14.0 — Linked Photo Video Library

## Photo → video pairing
- Owner can pair an already-made Telegram video with an exact library photo during `/libraryimport`.
- Upload order: `photo → video → next photo → video`. The video always attaches to the most recently accepted photo.
- Video does not count toward the 10-photo-per-level limit.
- One photo can have zero or one linked video; sending another video before the next photo replaces the previous link.
- The linked video is stored as a Telegram `file_id`, so Railway redeploys do not require re-uploading media.

## User experience
- A library photo with a paired video gets an inline `🎬 Смотреть видео` button.
- Clicking it sends the owner-uploaded video; no Veo generation, image generation, or photo credit is consumed.
- Video access inherits the photo's character and relationship-level gate. A user cannot open a video for a photo that is not yet accessible.
- Linked videos work for ordinary library delivery, AI-failure library rescue, and story photos whenever the selected library item has a video.

## Database / migration
- Added nullable `linked_video_file_id`, `linked_video_unique_id`, and `linked_video_caption` to `photo_library_items`.
- Existing PostgreSQL installs are migrated automatically at startup.
- Existing photo libraries remain valid; photos without videos simply have no video button.

## Admin visibility
- `/library` now shows total linked-video count and per-scene video counts.
- The tenth photo no longer forces import preview immediately, so the owner can attach a video to photo 10 before pressing Finish.

Veo remains independent and is not required for linked owner-uploaded videos.
