# AnnaBot V3.11.0 — Launch Readiness + Character DNA + Collections + Quest Core

## Launch readiness
- Added `/terms`, `/privacy`, `/support`, `/delete_me`.
- First start now requires 18+ + Terms/Privacy consent.
- Text chat, photo requests, Premium, Collections and Stories are gated until consent.
- `/delete_me` removes messages, memories, relationship state, reminders, communication profile, collection seen-state, quest state and local payment records.
- Pre-checkout now validates XTR currency, product payload and expected amount instead of accepting everything.
- Owner command `/refundstars <telegram_id> <charge_id> [stars]` uses Telegram Star refund API and records local refund metadata.

## Character DNA / Competency Gate
- Added `data/characters/anna_dna.json` and future templates for Emily, Mia and Chloe.
- Anna now has explicit traits, relationship goal and skill levels.
- Coding/automotive/finance requests are classified against the character's actual competency.
- Anna no longer becomes a Python expert simply because the underlying LLM can code.
- Character DNA is injected into the conversation context without exposing numeric settings.
- L1/L2 relationship guidance now allows a little more mutual flirt/chemistry without forcing intimacy.

## Photo collection: item-level progress
- Added `UserSeenPhotoItem` for per-photo tracking.
- `/collection` and `🖼 Коллекция` show `opened / accessible` and level-by-level progress.
- Existing pack-level seen history is backfilled automatically so current users do not lose progress.
- Library importer is now optimized for 10 photos per level.
- A 10-photo import is stored as 3+3+3+1; the 10th photo is no longer discarded as an incomplete tail.

## Quest Core
- Added persistent `UserQuestProgress` and `QuestReplayOffer`.
- Added `🎯 Истории` / `/stories`.
- Initial stories:
  - `Что надеть?` (L1)
  - `Вечер Анны` (L2)
- First route becomes canonical and is written into long-term memory.
- Paid replay opens an alternative route without overwriting canonical memory.
- Alternative route price defaults to `QUEST_REPLAY_STARS=10`.
- Quest route rewards can deliver story photos without consuming daily free-photo quota; library is preferred, AI is fallback.
- Premium gets `PREMIUM_MONTHLY_QUEST_REPLAYS=2` free alternative-route replays per month.

## Premium
Premium now communicates value beyond photo credits:
- larger chat/memory allowance;
- 12 photo credits;
- 2 quest replays/month by default;
- more continuity/proactive behavior;
- early-access positioning for future character features.

## Safety / platform behavior
- Existing Telegram Stars flow remains intact for digital purchases.
- Existing QR/payment-method admin infrastructure is preserved but not wired as a replacement for Stars digital checkout.
- Existing GPT Image 2 / Seedream 4.5 routing, canonical Anna identity V3.10.7 and library rescue remain intact.

## Test status
- Python compileall: PASS.
- 27 selected static/regression tests: PASS.
- V3.11 runtime SQLite smoke: PASS for 10-photo import, 5/10 collection progress, canonical quest memory, paid alternate route and full user-data deletion.
- Full pytest cannot run in the artifact environment because `aiogram` and `openai` are not installed and outbound pip is unavailable; Railway installs them from requirements.txt.
