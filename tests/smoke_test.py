from pathlib import Path
import ast, json, re
ROOT=Path(__file__).resolve().parents[1]
for p in ROOT.rglob('*.py'):
    if '.venv' not in p.parts:
        ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
character=json.loads((ROOT/'data/characters/anna.json').read_text(encoding='utf-8'))
assert character['id']=='anna_01'
for ref in character['visual_identity']['reference_assets']:
    assert (ROOT/character['visual_identity']['reference_folder']/ref).exists(), ref
assert 'gpt-image-2' in (ROOT/'config.py').read_text(encoding='utf-8')
active='\n'.join(p.read_text(encoding='utf-8',errors='ignore') for p in ROOT.rglob('*') if p.is_file() and p.suffix in {'.py','.md','.json'} and p.name!='smoke_test.py')
legacy=[r'Quiero que actúes',r'Tu configuracion',r'Accion cancelada',r'/finalizar',r'Algo salió']
assert not any(re.search(x,active,re.I) for x in legacy)
print('STATIC_SMOKE_OK')
