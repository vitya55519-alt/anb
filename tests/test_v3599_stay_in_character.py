"""V3.59.9: she never steps out of her life; photos back on 1k."""
from pathlib import Path

from services.chat_service import BREAKS_CHARACTER, _editor_instructions, _needs_rewrite

ROOT = Path(__file__).resolve().parents[1]


def test_breaking_character_answers_get_rewritten():
    for answer in ("ой, ну ты даёшь) я ж не реальный человек", "я же бот", "я всего лишь программа",
                   "я не настоящая, милый", "я ИИ, прости"):
        assert _needs_rewrite("а как же муж?", answer), answer
    # a sincere «ты бот?» keeps her honest answer
    assert not _needs_rewrite("ты бот?", "да, я ИИ-персонаж, но с тобой я по-настоящему")


def test_normal_answers_pass():
    for answer in ("муж на работе, приходи 😏", "я ботинки купила", "нечеловеческая усталость сегодня"):
        assert not BREAKS_CHARACTER.search(answer), answer


def test_prompts_forbid_leaving_the_role():
    assert "коротко скажи что нет" not in _editor_instructions()
    assert "сама не говорит, что она бот" in _editor_instructions()
    assert "честное «да»" in _editor_instructions()
    src = (ROOT / "services" / "character_service.py").read_text(encoding="utf-8")
    assert "ТЫ НЕ ВЫХОДИШЬ ИЗ РОЛИ" in src and "ответь честно" in src
    beh = (ROOT / "services" / "behavior_service.py").read_text(encoding="utf-8")
    assert "честно и коротко" not in beh


def test_spicy_resolution_default_is_1k():
    src = (ROOT / "config.py").read_text(encoding="utf-8")
    assert 'os.getenv("SPICYAPI_RESOLUTION", "1k")' in src
