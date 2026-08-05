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
for ref in ('00_identity_face_new.png','00_seedream_face_safe.png','02_full_body_white_top.png'):
    assert (ROOT/character['visual_identity']['reference_folder']/ref).exists(), ref
cfg=(ROOT/'config.py').read_text(encoding='utf-8')
assert 'gpt-image-2' in cfg
assert 'fal-ai/bytedance/seedream/v4.5/edit' in cfg
assert 'FAL_KEY' in cfg
assert 'PHOTO_ROUTER_MODE = os.getenv("PHOTO_ROUTER_MODE", "hybrid")' in cfg
assert 'PHOTO_SET_SIZE' in cfg
photo=(ROOT/'services/photo_service.py').read_text(encoding='utf-8')
main=(ROOT/'main.py').read_text(encoding='utf-8')
assert 'https://fal.run/' in photo
assert "request.scene == 'lingerie'" in photo
assert "return 'openai'" in photo
assert 'OUTFIT_POOLS' in photo and 'HAIRSTYLE_POOL' in photo and 'SHOT_VARIANTS' in photo
assert 'IDENTITY_LOCK' in photo and 'NEGATIVE_BLOCK' in photo
assert 'generate_photo_set' in photo
assert 'static fallback' not in photo.lower()
assert "'personal': 4" in photo
assert 'locked:' in main and 'retry_photo:' in main
assert 'ReplyKeyboardMarkup' in main
assert 'FREE_PHOTOS_LEVEL_1_2' in cfg and 'FREE_PHOTOS_LEVEL_3_6' in cfg
assert 'return FREE_PHOTOS_LEVEL_3_6 if level >= 3 else FREE_PHOTOS_LEVEL_1_2' in photo
active='\n'.join(p.read_text(encoding='utf-8',errors='ignore') for p in ROOT.rglob('*') if p.is_file() and p.suffix in {'.py','.md','.json'} and p.name!='smoke_test.py')
legacy=[r'Quiero que actúes',r'Tu configuracion',r'Accion cancelada',r'/finalizar',r'Algo salió']
assert not any(re.search(x,active,re.I) for x in legacy)
print('STATIC_SMOKE_OK')
