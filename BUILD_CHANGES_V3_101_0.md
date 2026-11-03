# V3.101.0 — personal evening and pushes on his last topic

Backup 2026-11-03: replies to ritual/proactive messages within 3 h — proactive 1 of 136,
morning ritual 3%, evening ritual 10%, «life event» 10%, retention push 8%.

- Evening ritual (scheduler `_rituals`): `chat_service.morning_callback(evening=True)` asks «как прошёл
  день» tied to something she knows about him (memories, last talk; window 72 h, needs 3+ of his
  messages). Falls back to the template line when there is nothing to pick up. Event `evening_callback_sent`.
  The evening's «а завтра утром пришлю…» promise still rides after it.
- Pushes after 24 h of silence (`_proactive`): the tier-1 «miss»/cliffhanger push and the tier-2 push now
  use `proactive_reply(topic=True)` — she returns to the EXACT topic of his last talk and asks one concrete
  question (needs 2+ of his messages in the last 8). Static texts remain the fallback.
  `retention_push_sent.kind` becomes `miss_topic` / `cliffhanger_topic` to measure the change.

Stacked on V3.100.0 (PR #119) → V3.99.0 (PR #118).
