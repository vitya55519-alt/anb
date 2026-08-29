from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'services/photo_service.py').read_text(encoding='utf-8')
ast.parse(text)
assert "SEEDREAM_ADULT_SCENES = {'personal', 'lingerie', 'private_fashion', 'nude', 'tease'}" in text
assert 'request.scene in SEEDREAM_ADULT_SCENES or INTIMATE_STYLE.search' in text
assert "return 'seedream45'" in text
assert "return 'openai'" in text
assert 'PHOTO_SET_SIZE' in text
assert 'WARDROBE_LEVEL_POOLS' in text
assert 'PACK_TIER_RULES' in text
assert 'SEASON_RULES' in text
print('PHOTO_ROUTING_STATIC_OK')
