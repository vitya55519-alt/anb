from pathlib import Path
import ast, json, re
ROOT=Path(__file__).resolve().parents[1]
for p in ROOT.rglob('*.py'):
    if '.venv' not in p.parts:
        ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
character=json.loads((ROOT/'data/characters/anna.json').read_text(encoding='utf-8'))
assert character['id']=='anna_01'
assert character['visual_identity']['identity_version']=='anna_v2_new_face_2026_08'
for ref in character['visual_identity']['reference_assets']:
    assert (ROOT/character['visual_identity']['reference_folder']/ref).exists(), ref
for ref in ('00_identity_face_new.png','00_seedream_face_safe.png','00_openai_safe_fullbody.png','02_full_body_white_top.png'):
    assert (ROOT/character['visual_identity']['reference_folder']/ref).exists(), ref
cfg=(ROOT/'config.py').read_text(encoding='utf-8')
assert 'gpt-image-2' in cfg
assert 'fal-ai/bytedance/seedream/v4.5/edit' in cfg
assert 'FAL_KEY' in cfg
assert 'PHOTO_ROUTER_MODE = os.getenv("PHOTO_ROUTER_MODE", "hybrid")' in cfg
assert 'PHOTO_SET_SIZE' in cfg
photo=(ROOT/'services/photo_service.py').read_text(encoding='utf-8')
main=(ROOT/'main.py').read_text(encoding='utf-8')
adapt=(ROOT/'services/adaptation_service.py').read_text(encoding='utf-8')
models=(ROOT/'models/app_models.py').read_text(encoding='utf-8')
chat=(ROOT/'services/chat_service.py').read_text(encoding='utf-8')
assert 'https://fal.run/' in photo
assert "request.scene in {'personal', 'lingerie', 'private_fashion'}" in photo
assert "return 'openai'" in photo
assert 'OUTFIT_POOLS' in photo and 'WARDROBE_LEVEL_POOLS' in photo and 'HAIRSTYLE_POOL' in photo and 'SHOT_VARIANTS' in photo
assert 'PACK_TIER_RULES' in photo and 'LEVEL_VISUAL_RULES' in photo and 'SEASON_RULES' in photo
assert 'PROGRESSION PACK FRAME' in photo
assert "'club': 5" in photo and "'bar': 4" in photo and "'shop': 2" in photo
assert 'generate_photo_set' in photo
assert 'static fallback' not in photo.lower()
assert 'locked:' in main and 'retry_photo:' in main
assert 'ReplyKeyboardMarkup' in main
assert 'FREE_PHOTOS_LEVEL_1_2' in cfg and 'FREE_PHOTOS_LEVEL_3_6' in cfg
assert 'return FREE_PHOTOS_LEVEL_3_6 if level >= 3 else FREE_PHOTOS_LEVEL_1_2' in photo
assert 'CommunicationProfile' in models
assert 'observe_message' in chat and 'maybe_analyze_profile' in chat and 'build_adaptation_context' in chat
assert 'АДАПТАЦИЯ К СОБЕСЕДНИКУ' in adapt
assert 'preferred_language' in adapt and 'slang_json' in models and 'visual_json' in models
assert 'observe_photo_preference' in adapt and 'get_visual_preferences' in adapt
assert "if request:\n            await handle_photo_request" in main
active='\n'.join(p.read_text(encoding='utf-8',errors='ignore') for p in ROOT.rglob('*') if p.is_file() and p.suffix in {'.py','.md','.json'} and p.name!='smoke_test.py')
legacy=[r'Quiero que actúes',r'Tu configuracion',r'Accion cancelada',r'/finalizar',r'Algo salió']
assert not any(re.search(x,active,re.I) for x in legacy)
assert '00_openai_safe_fullbody.png' in photo
assert 'safe_prompt=true' in photo
assert 'FAL_RETRIES' in cfg and 'FAL_CONNECT_TIMEOUT_SECONDS' in cfg
assert "request_label=f'{request.scene}:{i + 1}/{PHOTO_SET_SIZE}'" in photo
assert 'per_request=1' in photo
assert 'httpx.ReadTimeout' in photo
assert "num_images': num_images" in photo
# V3.9 Commercial Core
analytics=(ROOT/'services/analytics_service.py').read_text(encoding='utf-8')
state=(ROOT/'services/state_service.py').read_text(encoding='utf-8')
assert 'onboard:abilities' in main and 'onboard:meet' in main
assert '_photo_jobs' in main and 'asyncio.create_task(_run_photo_background' in main
assert 'photo_feedback:' in main
assert 'SAFE RETRY' in photo and 'on_frame' in photo and 'photo_partial' in photo
assert 'OPENAI_LEVEL_VISUAL_RULES' in photo
assert 'ProductEvent' in models and 'budget_allows_photo' in analytics
assert 'd1_retention' in analytics and 'photo_first_frame_ready' in analytics
assert 'DAILY_IMAGE_BUDGET_USD' in cfg and 'MONTHLY_IMAGE_BUDGET_USD' in cfg
assert 'ensure_life_state' in state and 'pending_hook' in state
print('STATIC_SMOKE_OK')
