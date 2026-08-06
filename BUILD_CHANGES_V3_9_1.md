# V3.9.1 — Relationship + Telegram Photo Library

Implemented:
- OpenAI photo-set `elapsed` NameError hotfix.
- Partial-frame delivery retained; one safety-preserving Seedream retry on HTTP 422 with a neutral fully-covered fashion prompt.
- Telegram `file_id` photo library: packs, items, seen-pack history and library-first free delivery at ~zero image-generation cost.
- Owner importer `/libraryimport`: character → scene → relationship level → progression/collection → up to 30 images; preview/save/undo/cancel.
- Owner stats `/library` grouped by character, scene and level.
- Multi-character content-library schema with Anna and disabled/public-soon Alena placeholder.
- `👩 Персонажи` fake-door measurement for Alena; click tracked as `fake_door_click`.
- Six-stage relationship naming refreshed: Знакомство → Симпатия → Доверие → Близость → Особая связь → Наша история.
- Hidden relationship dimensions: familiarity, continuity and connection alongside relationship/trust/intimacy.
- Relationship milestones persisted and surfaced naturally in profile/context.
- Absence no longer reduces earned relationship level.
- User-influenced fictional life state via `/today` or `/plans` and contextual vague-photo routing (e.g. “покажись” uses the current story location when appropriate).
- Seedream 5.0 offline prompt pack for generating curated library assets.
