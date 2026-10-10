# V3.57.8 — faster replies + no third hand in photos

## Faster chat replies
- `services/chat_service.py`: memory extraction and style analysis (two extra
  LLM calls) no longer block the reply — they run in the background after the
  answer is returned. The adaptation context is built once instead of twice.
- `services/llm_provider_service.py`: explicit timeouts on every LLM client.
  MiniMax and Gemini: 25 s, no SDK retries; OpenRouter (last fallback): 40 s,
  1 retry. Before, the SDK default was 600 s + 2 retries, so a hung provider
  kept the user waiting for minutes before the fallback started.
  Tunable via `LLM_TIMEOUT_SECONDS` / `LLM_FALLBACK_TIMEOUT_SECONDS`.

## Photos: no third hand
- Owner screenshot: mirror selfie with the «shush» expression rendered three
  hands (finger at lips + phone + hand on hip).
- `services/photo_expression_service.py`: `shush` and `blow_kiss` now use the
  one free hand (the other one if she holds a phone).
- `services/photo_service.py`: new `HANDS_RULE` line in every photo prompt
  (exactly two arms/hands; in a phone selfie only one hand is free) and
  «a third hand or arm, more than two hands» added to `NEGATIVE_BLOCK`.

## Tests
- `tests/test_v3578_speed_hands_static.py`
