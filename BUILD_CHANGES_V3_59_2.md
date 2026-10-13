# V3.59.2 — studio uploads work again + three day-0/day-1 hooks

- **Studio «Такое описание нельзя» on any uploaded photo.** aiohttp's default request cap is 1 MB; the photo travels as base64 JSON, so a normal phone photo overflowed it, the body parsed as empty and the user got the «banned prompt» toast. Cap raised to 12 MB, the browser now shrinks uploads to ≤1600 px JPEG, and the toast names the real problem (bad photo / banned words / other). Uploaded photos still never go to the uncensored engine (they may be real people).
- **Welcome selfie:** right after her first hello she sends a free selfie (rendered in the background; also lands in the app chat).
- **Chat openers in the app:** while a dialog has fewer than 4 user messages, three tap-to-send chips — «Привет 😊», «Расскажи о себе», «Покажи себя 📸».
- **Evening promise:** when her media pool has a photo, the evening ritual ends with «а завтра утром пришлю тебе кое-что 🙈» and the morning ritual opens with «как обещала 🙈» + the photo.
