# BUILD CHANGES V3.19.10 — liveness page on the bare Railway domain

Opening `https://<app>.up.railway.app/` in a browser showed aiohttp's default
`404: Not Found` because the tiny web server only registered `/healthz` and
the three FreeKassa routes. The owner read that 404 as a broken deploy.

## Change

- `main.py`: new `_root` handler registered as `GET /` returning a plain-text
  liveness page: "AnnaBot web endpoint is alive. Health check: /healthz".
- The 404 was never a failure: it was our own web server answering for an
  unregistered path, which also proves the public domain and PORT wiring work.

## Check

- `GET /` -> 200 liveness text.
- `GET /healthz` -> 200 `ok` (use this URL in the FreeKassa merchant form check).
