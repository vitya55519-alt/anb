from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_anna_emoji_baseline_is_warmer_but_bounded():
    text = (ROOT / "services/character_service.py").read_text(encoding="utf-8")
    assert "обычно 1, нередко 2" in text
    assert "не заканчивай постоянно одним и тем же 😏" in text
    assert "обычно 0–1" not in text

def test_adaptation_mentions_emoji_preference():
    text = (ROOT / "services/adaptation_service.py").read_text(encoding="utf-8")
    assert "emoji_pref" in text
    assert "привычка к эмодзи" in text
    assert "базовый стиль Анны остаётся немного эмоциональнее" in text
