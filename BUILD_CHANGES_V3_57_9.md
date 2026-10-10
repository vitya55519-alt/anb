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

## Follow-up after measuring production
The heavy storefront tiles are actually MP4 «living tiles» (2.3–3.2 MB each),
so two more fixes:
- `asset_version()` is now a content fingerprint (name + size + crc32 of the
  first/last 64 KB, cached) instead of the newest mtime. Railway redeploys and
  the DB→disk restore of card overrides gave every file a fresh mtime, so the
  `?v=` stamp changed on every release and all clients re-downloaded every
  tile video. Now the URL changes only when the media actually changes.
- `/webapp/card/{id}` (mp4/gif) and `/webapp/live/{id}` are served with
  `web.FileResponse` — Range requests (206) + sendfile, so the tile starts
  playing before the whole clip is downloaded.
