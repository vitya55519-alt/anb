# AnnaBot V3.12.0 — Gemini Dialogue + Veo Video Foundation

## Dialogue
- Added Gemini as an optional primary visible-chat provider through Google's official OpenAI-compatible Gemini endpoint.
- Default Gemini model: `gemini-3.5-flash` so the current AI Studio Free tier can be tested immediately. After billing is enabled, switch `GEMINI_CHAT_MODEL=gemini-3.6-flash` for the newest production Flash model.
- If `GEMINI_API_KEY` exists, `CHAT_PROVIDER` defaults to `gemini`; otherwise the bot keeps using OpenAI.
- OpenAI remains an automatic dialogue fallback (`CHAT_FALLBACK_OPENAI=true`).
- Gemini 3.x Flash calls intentionally omit deprecated `temperature/top_p/top_k` sampling parameters.
- Default Gemini thinking level is `minimal` to reduce companion-chat latency and overthinking.
- Dialogue, natural-language rewrite guard, and proactive messages all use the shared provider router.
- Background memory extraction/adaptation and existing image/TTS routes remain unchanged for reliability.

## Video
- Added a production-shaped Gemini/Veo image-to-video service.
- Video remains OFF by default (`GEMINI_VIDEO_ENABLED=false`) because Veo requires a paid Gemini API tier.
- Default economical model: `veo-3.1-lite-generate-preview`, 8 seconds, portrait 9:16, 720p.
- When enabled, Premium UI exposes `🎬 Оживить последнее фото` with a configurable Stars price (`VIDEO_COST_STARS`, default 100).
- The bot animates the user's most recently delivered Anna photo in a background task.
- Only one video job per user can run at once.
- If generation fails after payment, the bot attempts an automatic Telegram Stars refund and records the refund locally.
- Added `/geministatus` for the owner to inspect provider/video configuration without exposing secrets.

## Deployment
Add `GEMINI_API_KEY` to Railway Variables. For chat only, video billing is not required. To enable video after Google billing is activated, set `GEMINI_VIDEO_ENABLED=true`.
