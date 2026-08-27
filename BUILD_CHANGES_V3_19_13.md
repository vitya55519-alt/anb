# BUILD CHANGES V3.19.13 — emoji variety + in-chat photo discoverability

Owner feedback: in chat the character kept repeating a single smiley, and a
new user could not tell that photos can be requested right inside the
conversation.

## Changes

- `services/character_service.py`:
  - New «ЭМОДЗИ» block in the persona prompt: varied mood-matched palette
    (😏 😉 😘 🥰 😈 🔥 🙈 😌 💕 ✨ 😍  🙄 😑 ), explicit rule to never
    repeat the same emoji in two consecutive messages, bounded 0–2 per
    message like a real person.
  - ФОТО block: she now occasionally tells the user herself that a photo can
    simply be asked for in chat («просто попроси фотку прямо здесь 😏»),
    because he may not know it is possible.
- `main.py` `abilities_text()`: the photo line now explicitly says
  «фото прямо в чате: напиши "скинь фото" или "хочу тебя увидеть"», so the
  /features screen teaches the behaviour. The backend already supported it:
  natural photo requests are routed to the photo pipeline, and her chat photo
  offer + user "да/скинь" triggers generation (existing v3.16 logic).
- `tests/test_v31913_..._static.py`: pins the emoji-variety block, the
  character hint line and the /features wording.
