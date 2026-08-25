# BUILD CHANGES V3.19.1 — Admin Free Constructor + Video Diagnostics

## 1. Admin free character creation
- Admins (`ADMIN_TELEGRAM_IDS`) skip the Stars invoice in the character
  constructor: the confirm screen shows "Создать · бесплатно (админ)" and
  `constructor:buy` starts generation directly with `charge=None`.
- `_finish_constructor` now accepts `charge: str | None`; the refund path
  only runs for paid runs, admin failures simply invite a retry.

## 2. Video engine diagnostics
- `_video_unavailable_text()` replaces the generic "Видео пока недоступно"
  alert in all three animation entry points (photo card, animate-last,
  motion preset picker). Admins now see a per-engine checklist
  (Gemini/Veo, Replicate, fal.ai, HF) with the missing env var named,
  so a broken Railway environment is diagnosable in one tap.

## Tests
- `tests/test_v319_wildgrl_features_static.py` extended with
  `test_admin_free_constructor` and `test_video_unavailable_diagnostics`.
