# V3.57.9 — Mini App loads fast again (web-sized images)

Owner report: «прогружает страницы медленнее в миниприложении».

Measured on production: storefront cards were the original 2–5 MB PNG/JPEG
files (`/webapp/card/anna_01` 2.57 MB / 2.9 s, darina 3.27 MB / 3.3 s). The
asset stamp changes on every deploy, so after each release every client
re-downloads all of them.

- `services/webapp_service.py`: new `web_image()` — JPEG/PNG/WebP of 300 KB+
  are downscaled to max 1280 px and re-encoded as WebP q82 (EXIF orientation
  respected, alpha kept). Results are cached in memory (96 entries); any
  decode error falls back to the original bytes. A 5 MB PNG becomes ~100 KB.
- `main.py`: `/webapp/card/{id}` and `/webapp/photo/{id}` serve the web-sized
  version; the conversion and file read run in a worker thread so the event
  loop (and the bot) never blocks. `character_photo()` itself still returns
  full quality — video circles keep using the original.
