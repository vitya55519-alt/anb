# V3.28.0 — persistent background-job registry (scaling foundation)

## Problem
Long-running generation tasks (photo, video, circle, constructor) existed only
as `asyncio.Task` handles in in-memory dicts (`_video_jobs`, `_photo_jobs`).
Every Railway redeploy killed them silently: the user paid / waited and got
nothing, and no other process could see or continue those jobs. This also
blocked any future multi-instance setup.

## What changed
- `models/app_models.py`: new `BackgroundJob` table (`background_jobs`) —
  telegram_id (BigInteger), kind, status, priority, payload_json, error,
  timestamps. Auto-created by `create_all`; existing DBs get it on startup.
- `services/jobs_service.py` (new): `begin_job` (supersedes stale active rows
  for the same user+kind), `finish_job`, `recover_stale_jobs` (startup sweep
  marking queued/running rows `recovered`, one entry per user).
- `main.py`: new `_spawn_job()` wrapper creates the DB row (priority=1 for
  premium users) and tracks the coroutine to `done`/`failed`. ALL 10 spawn
  sites of the long pipelines now use it. On startup the bot recovers stale
  jobs and asks affected users to retry.

## Scaling path this unlocks
1. **Now (single instance):** redeploys stop losing jobs; every generation is
   observable in the DB (`status`, `error`), premium jobs carry priority.
2. **Next (queue mode):** flip spawns to insert `status='queued'` rows and
   run a worker loop (`SELECT ... ORDER BY priority DESC, created_at`) —
   then a separate worker dyno can drain generation while the bot dyno chats.
3. **Later (horizontal):** webhook mode + N workers behind the same table;
   the unique active-job invariant per user+kind already holds across
   processes because `begin_job` runs inside the DB.

## Tests
- `tests/test_v3280_job_registry_static.py`: pins the model, the contract of
  `jobs_service`, that no untracked spawn of the long pipelines remains, that
  startup recovery runs before polling, plus runtime sqlite checks of
  begin/supersede/finish/recover/dedupe and error truncation.
