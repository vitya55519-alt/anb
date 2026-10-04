# V3.50.0 — Relationship path: romance ↔ debauchery branching

## Owner request
> «Сделать разветвление: в зависимости от выполнения заданий/квестов давать
> возможность ответа на вопрос квеста, и от этого у персонажа будет расти либо
> путь романтики, либо разврата; от этих ответов будет меняться общение в чате.»
> Plus: «игрок видел шкалу похоти/разврата — поместить на экран карточки
> персонажа.»

Locked design (owner decisions): ONE swing axis per character
(`path_axis`, −100 romance ↔ +100 bold), driven by quest route answers; the
bold end is real 18+ but always behind the existing `adult_confirmed` +
consent gates; the scale is shown on the character card under the closeness
bar with **qualitative labels only** («Нежная / Сбалансированная /
Раскрепощённая», «Нежность ↔ Страсть») — never a raw number.

## Data model (`models/relationship_models.py`)
- `UserCharacterRelationship.path_axis` (Float, default 0.0) — per-character
  axis clamped to [-100, 100]; a dimension distinct from `intimacy_score`
  (closeness growth vs. flavor of the bond). Auto-migrated by the `db.py`
  catch-all; the model registry already imports the class.

## Quest branching (`services/quest_service.py`)
- `ROUTE_INCLINATION` maps every `(quest, route)` to `romance` / `bold` /
  neutral (6 routes stay deliberately neutral). Two new dilemma quests join the
  roster with clean romance/bold forks: **«Поздно ночью»** (`late_night_text`,
  min_level 5) and **«Свечи или адреналин»** (`candle_or_adrenaline`,
  min_level 6) — they slot into the V3.49.0 unlock ladder automatically.
- `complete_route(..., character_id=None)`: only the FIRST canonical answer
  moves the axis (`PATH_STEP = 8`, clamped), so paid replays can't farm it.
  The axis belongs to the character actually being chatted — bot call sites
  pass `get_user_character(...)`.

## Chat tone (`services/relationship_engine.py`)
- `build_relationship_context` reads `row.path_axis`; at ≤ −40 it injects a
  tenderness line, at ≥ +40 a passion line («смелее, игривее, дерзче… но
  строго в рамках текущего этапа»). The stage frame remains the hard limit —
  the path only tilts the style inside it, never unlocks graphic content by
  itself. Threshold constant: `PATH_TONE_THRESHOLD = 40`.
- New helper `get_path_axis(user_id, character_id)` for gate checks.

## 18+ gating (`services/spicy_service.py` + `main.py`)
- `SpicySet.min_path` (default 0); the boldest set **«Только для тебя»**
  (nude, 🖤) now requires `path_axis >= 30` **in addition to** min_level 6 and
  the one-time 18+ confirmation. Enforced in `pre_checkout`, in
  `spicy:set:` callback, and surfaced as a separate lock row in the spicy
  keyboard («🔒 … нужна страсть в вашей связи»). Price stays Stars — the path
  never discounts the economy (V3.46.0 rule).

## Character-card indicator (`webapp_service.py` + `webapp/index.html`)
- Card payload gains `'path'` from `_batch_path_axis` (one batched query, no
  N+1, mirrors `_batch_rel_levels`).
- Under the «Уровень близости» bar a centered swing bar renders
  («💞 Характер связи»): purple-blue fill grows left = Нежность, warm-red fill
  grows right = Страсть, qualitative tag in the corner; hidden until a
  relationship row exists. ru/en i18n added.

## Tests
- `tests/test_v350_path_branching_static.py` — 6 checks (column, inclination
  map + dilemma quests, canonical-only axis move + per-character routing,
  qualitative tone injection, spicy min_path gate, card indicator payload +
  markup).
- Full suite: 17 failed / 906 passed / 1 error — exact baseline parity, +14
  new green since V3.48.3.

## Deploy notes
- Schema: one new Float column, auto-migrated on boot.
- `VERSION` not bumped (3.4x line).
- Existing completed stories keep their old canonical choices but never move
  the axis retroactively; from deploy on, every NEW first choice counts.
