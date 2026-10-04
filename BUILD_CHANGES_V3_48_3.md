# V3.48.3 — Daily-quest menu survives a transient failure

## Owner report
> «Кнопка "Задание", когда нажимаешь — результат на фото (пусто, „Не получилось
> ответить — попробуй ещё раз“). И какая ценность этих заданий?»

## Diagnosis
The «🎯 Задание» pill in the app chat opens the feature sheet via
`openFeature('quest')` → GET `/webapp/api/feature?kind=quest`. The quest branch
itself is pure and cannot fail (`couple_service.daily_quest` is a deterministic
md5 pick). The `reply_err` string only ever renders in that overlay when the GET
returns non-ok **or throws** — and the SPA's `fetch().json()` on a raw HTTP 500
throws, so it shows the generic «try again».

The 500 comes from the shared prologue of `_webapp_api_feature`:
`get_relationship_level → get_relationship_stage → ensure_user(telegram_id)`
performs a DB **write on every call**. On a cold start right after a Railway
redeploy (or any brief Postgres connection blip) that call can raise, the handler
has no guard, aiohttp returns 500, and the button looks broken.

## Fix
- **`main.py`** — `_webapp_api_feature` is now a thin exception-guarded wrapper
  over `_webapp_api_feature_impl`. Any unexpected error is logged with the real
  traceback (`logger.exception('webapp feature menu failed')`) and answered with
  a clean `{'ok': False, 'error': 'temporarily_unavailable'}` (HTTP 200) instead
  of a raw 500. The route still registers `_webapp_api_feature`.
- **`webapp/index.html`** — `openFeature` retries the fetch **once** (450 ms
  backoff) before showing «try again», so a transient blip self-heals and the
  quest/date/apartment/photo menus open normally on the second attempt.

## Value of the quests (owner question)
- **«🎯 Задание» in the chat** = the *daily quest* (V3.21.0): an honor-system
  prompt («сделай ей комплимент», «расскажи, как прошёл день» …). One per day,
  deterministic per user. Claiming it grants **+5 attention points**
  (`attention_points`) — a light daily-engagement nudge, no payment.
- **«Миссии» tab** (V3.46.0) = the structured roadmap with per-mission CTAs and
  bigger rewards (peaches / attention / unlocks) — this is where the meaningful
  progression lives.
- **Story quests** (`quest_service`, the bot's «Истории») unlock by relationship
  level and can grant a generated photo / an alternate branch (paid replay).

So the chat button is a small daily bonus; the real reward ladder is the Missions
tab. If the low value of the chat pill is the concern, we can either surface the
reward more clearly on the card or wire the pill to the Missions roadmap — a
product call for the owner.

## Tests
- **`tests/test_v3483_quest_resilience_static.py`** — 2 checks: the endpoint is
  exception-guarded (wrapper + impl + logging + route target) and `openFeature`
  retries once before the error.
- Full run: **17 failed / 892 passed / 1 error** — baseline parity (the same 17
  pre-existing pins) + the new green tests.

## Deploy notes
- No schema change. `VERSION` not bumped (3.48.x line).
