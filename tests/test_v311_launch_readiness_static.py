from pathlib import Path
import ast, json
ROOT=Path(__file__).resolve().parents[1]
for p in ROOT.rglob('*.py'):
    ast.parse(p.read_text(encoding='utf-8'), filename=str(p))
main=(ROOT/'main.py').read_text(encoding='utf-8')
app=(ROOT/'models/app_models.py').read_text(encoding='utf-8')
photo=(ROOT/'models/photo_models.py').read_text(encoding='utf-8')
quest=(ROOT/'services/quest_service.py').read_text(encoding='utf-8')
collection=(ROOT/'services/collection_service.py').read_text(encoding='utf-8')
behavior=(ROOT/'services/behavior_service.py').read_text(encoding='utf-8')
assert "Command('terms')" in main and "Command('privacy')" in main and "Command('delete_me')" in main
assert 'consent:accept' in main and 'class UserConsent' in app
assert 'query.currency' in main and 'QUEST_REPLAY_STARS' in main and 'refund_star_payment' in main
assert 'class UserSeenPhotoItem' in photo and 'collection_progress' in collection and '_backfill_from_seen_packs' in collection
assert "Command('collection')" in main and "Command('stories', 'quests')" in main
assert 'canonical_route' in (ROOT/'models/quest_models.py').read_text(encoding='utf-8')
assert 'needs_payment' in quest and 'premium_replays_left' in quest
assert 'task_character' in behavior
anna=json.loads((ROOT/'data/characters/anna_dna.json').read_text(encoding='utf-8'))
assert anna['competencies']['coding']==0 and anna['traits']['sexual_openness']>=0.7
assert (ROOT/'data/characters/emily_dna.json').exists() and (ROOT/'data/characters/mia_dna.json').exists() and (ROOT/'data/characters/chloe_dna.json').exists()
assert '10 / 10' in main
print('V311_LAUNCH_READINESS_STATIC_OK')
