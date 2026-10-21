# V3.69.0 — all video and circles on SpicyAPI

Owner (2026-10-21): «замкнуть фотки и видео на этот сайт». Gemini/Veo (broken
since the inlineData 400), Replicate (silent), fal (dead since 15 Oct) and the
HF spaces are out of every video chain.

## Engine
- services/spicy_video_service.py: `animate_image_spicy` — SpicyAPI
  createTask → recordInfo poll → mp4; MiniMax H3 image-to-video renders the
  voice with the picture. Billed on accept → ImageSpend row `spicyapi_video`.
- The start frame is parked in memory behind an unguessable token and served at
  `/webapp/vsrc/<token>` for ~30 min (SpicyAPI takes the frame by URL).
- Env (all optional): SPICYAPI_VIDEO_MODEL (minimax/h3-spicy/image-to-video),
  SPICYAPI_VIDEO_SAFE_MODEL (minimax/h3/image-to-video), SPICYAPI_VIDEO_RESOLUTION
  (480p), SPICYAPI_VIDEO_SECONDS (5), SPICYAPI_VIDEO_TIMEOUT (420),
  SPICYAPI_VIDEO_COST_PER_SECOND_USD (0.038).
- All 7 call sites (bot «Оживить», bot circle, live tiles, studio video, app
  circle, app video, «🎬 Оживить» under a chat photo) use `video_engines()`.

## Circles like the owner's example
- Square frame (top-biased crop) so the result fits a Telegram video note.
- Prompt: handheld front-camera selfie, talking to him, lip-synced Russian line.
- The line comes from the dialogue: the first sentence(s) of her last reply,
  ≤ ~90 chars; stock phrases only as a fallback.

## Safety line (same as photos)
- Studio video (user's upload or prompt frame) always runs the regular H3 model
  with a forced fully-clothed, non-sexual prompt (`safe=True`); uploads stay
  admin-only (V3.64.6). The «spicy» model only animates her own generated frames.

Old service modules (gemini_video_service, hf_video_service, replicate/fal in
cloud_video_service) are no longer imported by main.py.

## Not tested live
The container cannot reach spicyapi.ai; the first real job should be checked
from the owner's PC / Railway logs («SpicyAPI video task …»).
