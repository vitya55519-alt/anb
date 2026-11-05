# V3.105.0 — no English words inside Russian replies

Seen live 5 Nov 2026: «понимаю, немного переживать нормально, especially когда это важное дело».

- `services/lang_guard.py`: `RU_DIRECTIVE` before his message in Russian talks («ни одного английского
  слова посреди фразы»); `stray_english()` finds Latin words in a Cyrillic reply, skipping brands
  (Premium, Telegram, iPhone, BMW…), ALL-CAPS, links/@names and words he wrote himself.
- `chat_service._fix_stray_english`: one short corrector call (`purpose=lang_repair`, temperature 0) swaps
  only those words; the original stays when the fix fails, changes the length too much, or still has them.
  Event `lang_repair`.
- Flag: `LANG_RU_PURITY_ENABLED` (default on). Tests: `tests/test_v3105_stray_english.py`.
