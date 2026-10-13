# V3.58.2 — SpicyAPI back on its feet: Seedream 5.0 Pro

- Root cause of spicyapi 0 ✅ / 39 ❌: the bot asked for `bytedance/seedream-5.0-lite/*`, which is no longer in the SpicyAPI catalog, and sent an undocumented `size` field (SpicyAPI rejects unknown fields with 400). Every job failed, so photos fell through to fal (filters nudity) and Gemini (quota 429).
- Defaults now: `bytedance/seedream-5.0-pro/edit` and `bytedance/seedream-5.0-pro/text-to-image`, input `aspect_ratio: 3:4`, `resolution: 1k` ($0.036/job), `enable_thinking: false` (faster).
- New env knobs: `SPICYAPI_RESOLUTION` (1k/2k), `SPICYAPI_ENABLE_THINKING` (0/1).
- createTask's 202 envelope is accepted.
- «🩺 Отказы» now shows the real SpicyAPI reason (e.g. `SpicyAPI error: 400 …`) instead of a bare `empty_result`.
- `SPICYAPI_ESTIMATED_COST_USD` default 0.0345 → 0.036.

If Railway has `SPICYAPI_IMAGE_MODEL` / `SPICYAPI_T2I_MODEL` set to a lite id, delete those variables.
