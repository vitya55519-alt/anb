# BUILD CHANGES V3.19.12 — video motion preset buttons fixed

The "💋 Поцелуй / 🤗 Обнимашки / 💃 Танец / ✨ Авто" buttons shown after
"Оживить это фото" looked dead: pressing them did nothing.

## Root cause

`video_preset_cb` unpacked the callback `videopreset:<preset>:<id>` with
`preset, _, raw_id = parts`, so `preset` received the router prefix
`'videopreset'`, failed the `VIDEO_PRESETS` membership check and the handler
silently returned after `cq.answer()`. `/videotest` bypasses the menu, which
is why the engine chain itself worked while the buttons did not.

## Fix

- `main.py`: unpack as `_, preset, raw_id = parts` so the chosen preset
  reaches `_video_gate` -> `_run_video_background`, and the engine
  (Gemini/Veo, Replicate hailuo, fal) receives the matching motion prompt
  (kiss / hug / dance). `auto` keeps the scene-aware default.
- `tests/test_v31912_video_preset_buttons_static.py`: pins the correct
  unpack, the preset hand-off into `_video_gate`, and that all three presets
  carry identity-preserving motion prompts.

## Notes

- "Failed to reconnect to upstream server" seen in Railway logs is Railway
  infrastructure noise, not bot code (string absent from the repo).
