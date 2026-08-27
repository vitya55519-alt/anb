# BUILD CHANGES V3.19.4 — Replicate-first video, Gemini/Veo removed

Owner decision: Gemini/Veo video is dropped completely (no paid Google
billing is connected). Replicate becomes the primary image-to-video engine.

## Removed
- `services/gemini_video_service.py` deleted; the Veo `predictLongRunning`
  integration is gone from the engine chain, diagnostics and config.
- All `GEMINI_VIDEO_*` settings removed from `config.py`.
- Gemini line removed from the admin video-unavailable checklist.
- `GeminiVideoError` replaced by the existing `CloudVideoError` in the
  unified video job. Gemini keeps ONLY chat fallback + image duties, still
  gated by the v3.19.3 `GEMINI_API_KEY_VALID` check.

## Video engine chain
Order is now **Replicate -> fal.ai -> HF spaces**; everything else
(presets kiss/hug/dance/auto, admin diagnostics, `/videotest`, automatic
Stars refund on total failure) is unchanged.

## Model upgrade
- Default `REPLICATE_VIDEO_MODEL` is now `minimax/hailuo-2.3-fast`:
  optimized for realistic human motion and expressive faces — the best fit
  for the kiss/hug/dance animation presets — at a moderate per-run cost.
- New `_replicate_image_param()` maps the input-image key per model owner
  (`first_frame_image` for minimax, `img` for wan-*, `image` for the rest),
  so swapping models via env does not require a code change.

## Action required on Railway
Add `REPLICATE_API_TOKEN` (replicate.com → Account → API tokens) to the
service Variables. No Gemini billing is needed for video anymore.

## Tests
- New `tests/test_v3194_replicate_first_video_static.py` (6 tests).
- Updated pins in test_v312, test_v3151, test_v3157, test_v3164,
  test_v3165, test_v3166, test_v3193.
