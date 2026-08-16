# AnnaBot V3.10.1 — Dialogue Architecture Fix

## Character cards
- Public second-character name changed from **Алёна** to **Emily**.
- Internal `alena_01` id is intentionally retained for backward compatibility with existing PostgreSQL/photo-library rows.
- Telegram admin card editor can still change the public display name at any time without deploy.

## Anna conversation quality
- Removed coffee from Anna's permanent stable-tastes profile and public card bio.
- Reduced cafe/coffee injection from fictional life-state presets.
- Added `dialogue_guard_service.py`: recent self-initiated motifs are cooled down so Anna does not recycle coffee/cafe, walks, home, gym, food or outfit filler every few messages.
- User-raised themes always override the cooldown.

## Technical requests
- Added companion-first task routing.
- Broad code requests such as “напиши калькулятор на Python” no longer immediately dump a full solution: Anna asks one concrete clarification first.
- Specific requests (CLI/GUI/features/full code/etc.) execute immediately.
- A short follow-up to Anna's clarification unlocks the implementation without another question loop.
- Technical answers retain a minimal Anna voice but avoid flirt/service boilerplate.
