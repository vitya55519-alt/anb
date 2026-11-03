# V3.102.0 — «🎭 Фетиши»: Premium mode, any adult fantasy theme, fixed limits

Owner: «можно сделать режим, чтобы поговорить на любой секс-фетиш с моделью?»
Backup 2026-11-03: 45 of 106 users ask for explicit talk, and the explicit chat only played along
with fantasies from level 5 and only if he suggested one himself.

- `services/fetish_mode.py`: 17 themes (feet, she dominates, she submits, bondage, spanking, lingerie,
  costumes, voyeurism, risky places, partner watches, threesome, teasing, sensory, massage, latex,
  dirty talk, humiliation-as-play) + a custom theme typed by him (80 chars). Stored in
  `DialogStore('fetish_mode')`, active 24 h, one theme at a time. Events: `fetish_mode_on`.
- `chat_service.reply`: when the mode is on, Premium (or admin) and confirmed 18+, the girl gets a
  «РЕЖИМ ФЕТИШЕЙ» director note: she opens and leads the theme at ANY relationship level, explicit
  style on (`wild`). Without Premium the mode is never injected — the Premium-only intimacy rule
  from V3.90.0 stays.
- Fixed limits (prompt + custom-text filter `_BLOCKED`): both adults, mutual consent and play, no
  violence or coercion, nothing involving minors or anything that reads as one, no animals, no blood
  or injury. A custom theme touching these is refused; if the talk drifts there she turns the scene
  back in character.
- Mini App: «🎭 Фетиши» in «Возможности» → sheet with the theme list, custom input, «Выключить».
  API: `GET /webapp/api/fetishes`, `POST /webapp/api/fetish/set`, `POST /webapp/api/fetish/stop`
  (errors `locked` / `premium_required` / `adult` / `refused`). Saves her opening line into the chat.
- Tests: `tests/test_v3102_fetish_mode.py`; `test_v3900_intimacy_premium_support` pin updated for
  `wild=plot_heat == 'wild' or bool(fetish_line)`.
