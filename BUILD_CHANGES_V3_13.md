# AnnaBot V3.13.0 — Onboarding + Quest UX + Nano Banana Reliability

## User onboarding
- Removed `🎭 Образы` from the persistent user menu. Old cached Telegram keyboards are redirected into `📸 Фото` for backward compatibility.
- `/start` now leads to a character picker after 18+/terms consent.
- Anna is visibly open; non-live characters are visibly locked/coming soon.
- Selecting Anna sends her photo + character description first, then a second capabilities message.
- If no Telegram card photo was configured, Anna's canonical face reference is used as the card fallback.
- Added `✨ Возможности` and `/features` so the capabilities screen can be reopened later.

## Quest UX
- Stories now show clear states: available / locked by relationship level / completed.
- Expanded the vertical quest path across L1-L6.
- L1 is surfaced during onboarding.
- New stories automatically announce themselves when the relationship crosses their unlock level.
- First route remains canonical; alternate paid/Premium replay does not rewrite canonical memory.
- Route completion continues to deliver the route-specific story photo.

## Nano Banana reliability
- Replaced the experimental Python `client.interactions.create()` wrapper in the photo path with the documented Gemini REST Interactions endpoint.
- UTF-8 prompt text remains JSON; reference images remain base64 blocks.
- Added explicit API-key validation and clearer HTTP failure reasons.
- REST response parser reads generated images from `steps[].content[]` image blocks.
- GPT Image 2 fallback and Library Rescue remain unchanged.

Video behavior was intentionally not changed in this release.
