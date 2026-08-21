from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_anna_emoji_baseline_is_warmer_but_bounded():
    text = (ROOT / "services/character_service.py").read_text(encoding="utf-8")
    # Natural chat style replaced the fixed emoji-count quotas; emoji are used
    # as ordinary human reactions instead of a counted quota rule.
    assert "пиши как реальный человек в личке" in text
    assert "обычно 0–1" not in text

def test_adaptation_mentions_emoji_preference():
    text = (ROOT / "services/adaptation_service.py").read_text(encoding="utf-8")
    assert "emoji_pref" in text
    assert "привычка к эмодзи" in text
    assert "базовый стиль Анны остаётся немного эмоциональнее" in text
