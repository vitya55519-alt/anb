# V3.59.1 — app polish

- **Blank screen on launch fixed.** No tab section was `active` at boot, so the app opened on an empty page until a nav button was tapped. The characters tab is active from the first paint; a 💗 splash shows while the SDK and the roster load; a failed load shows «Не получилось загрузить» + «Повторить» instead of a dash. The Telegram SDK tag moved to the end of the body (still before the app script; preload kept) so the splash paints immediately.
- **Daily tasks are checked, not trusted.** «✅ Я сделал · проверить» looks at today's own messages (compliment / pet name / dream question / red / a real story of the day / a voice message). Not done → «Сначала сделай это в чате с ней 😉», nothing credited.
- **Apartment explains itself** with an intro line; apartment actions and tasks get the emoji burst.
- **Save photo:** «⬇️ Скачать фото» under every chat photo and in the full-screen viewer (Telegram native download on 8.0+, browser fallback).
- **First minute is hers:** no referral link and no donation ask after 18+; the weekly donation reminder starts on day 3.
