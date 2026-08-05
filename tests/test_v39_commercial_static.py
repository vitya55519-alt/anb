from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]

for p in ROOT.rglob('*.py'):
    ast.parse(p.read_text(encoding='utf-8'), filename=str(p))

main = (ROOT / 'main.py').read_text(encoding='utf-8')
photo = (ROOT / 'services/photo_service.py').read_text(encoding='utf-8')
analytics = (ROOT / 'services/analytics_service.py').read_text(encoding='utf-8')
state = (ROOT / 'services/state_service.py').read_text(encoding='utf-8')
rel = (ROOT / 'services/relationship_service.py').read_text(encoding='utf-8')
models = (ROOT / 'models/app_models.py').read_text(encoding='utf-8')
cfg = (ROOT / 'config.py').read_text(encoding='utf-8')

assert "onboard:abilities" in main and "onboard:meet" in main
assert "_photo_jobs" in main and "asyncio.create_task(_run_photo_background" in main
assert "сек 😄 сейчас выберу нормальные кадры" in main
assert "photo_requested" in main and "admin_snapshot" in main
assert "Command('stats', 'adminstats')" in main

assert "on_frame" in photo
assert "photo frame delivered" in photo
assert "SAFE RETRY" in photo and "moderation_blocked" in photo
assert "photo_partial" in photo
assert "partial_{delivery_type}" in photo
assert "OPENAI_IMAGE_ESTIMATED_COST_USD" in photo
assert "photo_first_frame_ready" in photo

assert "class ProductEvent" in models
assert "d1_retention" in analytics and "d3_retention" in analytics and "d7_retention" in analytics
assert "budget_allows_photo" in analytics
assert "DAILY_IMAGE_BUDGET_USD" in cfg and "MONTHLY_IMAGE_BUDGET_USD" in cfg

assert "ensure_life_state" in state and "pending_hook" in state
assert "relationship_level_up" in rel

print('V39_COMMERCIAL_STATIC_OK')
