from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_v3121_nano_config_and_routing():
    cfg=(ROOT/'config.py').read_text(encoding='utf-8')
    photo=(ROOT/'services/photo_service.py').read_text(encoding='utf-8')
    req=(ROOT/'requirements.txt').read_text(encoding='utf-8')
    assert 'GEMINI_IMAGE_MODEL' in cfg and 'gemini-3.1-flash-image' in cfg
    assert 'GEMINI_IMAGE_ENABLED' in cfg
    assert 'google-genai' in req
    assert '_run_gemini_set' in photo
    assert "return 'gemini_image'" in photo
    assert "request.scene in {'personal', 'lingerie', 'private_fashion', 'nude', 'tease'}" in photo
    # Gemini failure path: OpenAI when available, otherwise Seedream.
    assert "fall back to Seedream" in photo

def test_v3121_anna_is_more_sensual_but_non_graphic():
    dna=(ROOT/'data/characters/anna_dna.json').read_text(encoding='utf-8')
    prompt=(ROOT/'services/character_service.py').read_text(encoding='utf-8')
    rel=(ROOT/'services/relationship_engine.py').read_text(encoding='utf-8')
    assert 'sensuality' in dna and 'playful_teasing' in dna
    assert 'ФЛИРТ И ЧУВСТВЕННОСТЬ' in prompt
    # Wording was refreshed by the natural/flirty style rewrite.
    assert 'Лёгкая пошлость — это нормально' in prompt
    assert 'Без графического секса и анатомических деталей' in prompt
    assert 'заметный чувственный флирт' in rel
