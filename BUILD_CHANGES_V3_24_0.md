# V3.24.0 — intimate photo reliability, constructor fix, POV video

## 1. Intimate photos actually generate now (Seedream safety checker)

Symptom: paid «Будуар»/lingerie sets died with `(gemini_image/http_400)` even
though Seedream can produce boudoir frames. Root cause: only `nude`/`tease`
ran Seedream with fal's safety checker disabled; `lingerie`, `personal` and
`private_fashion` kept the checker ON, fal's API-level moderation rejected the
prompt (4xx), the safe retry often followed, and the final fallback landed on
Gemini which 400s on any intimate framing.

Fix: new `SEEDREAM_ADULT_SCENES = {'personal', 'lingerie', 'private_fashion',
'nude', 'tease'}` in `services/photo_service.py`. `_run_seedream_set` uses it
for `allow_adult` (safety checker off for every intimate scene), and hybrid
routing uses the same set. Upstream gates are unchanged: relationship level,
18+ confirmation and paid delivery still apply per scene. The moderation-safe
retry on fal 4xx stays as a backstop and still runs with the checker ON and
fully covered wardrobe.

## 2. Transparent engine-chain errors

When the whole chain fails, the user/owner now sees every failed engine in
order, e.g. `(seedream45/FAL_KEY is not configured → gemini_image/http_400)`,
instead of only the last fallback. This makes misconfiguration (missing
`FAL_KEY` on Railway) instantly visible in the chat error line.

## 3. Constructor: admin «Создать · бесплатно» no longer loses the session

Root cause: the admin free path called `_finish_constructor(cq.message, None)`
and the function read `message.from_user.id` — for a callback message that is
the BOT, so the session lookup failed and the user got «что-то потерялось 😕».
Fix: `_finish_constructor` accepts an explicit `telegram_id`; the admin path
passes `cq.from_user.id`. The paid Stars path is unchanged (payment message
`from_user` is the real user).

## 4. POV video: she hugs/kisses the viewer, not herself

The `hug` preset literally said "wraps her arms around herself in a cozy
self-hug". Both `kiss` and `hug` presets in `services/cloud_video_service.py`
now state "The camera is the viewer's eyes": she steps close, embraces the
viewer / presses a kiss toward the person holding the camera. Identity and
wardrobe locks preserved.

## Tests

`tests/test_v3240_intimate_reliability_pov_static.py` — 5 tests:
SEEDREAM_ADULT_SCENES coverage + routing, chain transparency, constructor
admin id, POV presets (no self-hug). Suite: 354 passed.

## Owner notes

- If intimate sets still fail after deploy, the chat error now shows the full
  chain — check that `FAL_KEY` is set in Railway env (Seedream is the engine
  that delivers boudoir/lingerie).
- No price or gate changes; no DB migration.
