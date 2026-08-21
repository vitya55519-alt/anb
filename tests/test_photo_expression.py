"""Tests for rule-based facial-expression detection in photo generation.

Photos used to always show the character with a hardcoded warm smile. The
expression is now derived from the mood of the user's message: compliment ->
smile, rudeness -> upset, sadness -> concerned, flirt -> teasing, else neutral.
"""
import os

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-for-static-tests-only")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from services.photo_expression_service import (  # noqa: E402
    detect_expression_key, expression_description, EXPRESSIONS,
)
from services.photo_service import PhotoRequest  # noqa: E402


def test_compliment_yields_smile():
    assert detect_expression_key("ты такая красивая") == "smile"
    assert detect_expression_key("обожаю тебя, спасибо") == "smile"
    assert detect_expression_key("beautiful photo") == "smile"


def test_rudeness_yields_upset():
    assert detect_expression_key("ты тупая") == "upset"
    assert detect_expression_key("дай фото быстрее") == "upset"
    assert detect_expression_key("stupid bot") == "upset"


def test_sadness_yields_concerned():
    assert detect_expression_key("мне сегодня грустно") == "concerned"
    assert detect_expression_key("я одинок") == "concerned"


def test_flirt_yields_teasing():
    assert detect_expression_key("хочу тебя поцеловать") == "teasing"
    assert detect_expression_key("обними меня") == "teasing"
    assert detect_expression_key("хочу тебя") == "teasing"


def test_broad_stems_do_not_false_trigger():
    # Bare "давай" / "хочу" must NOT trigger anything — too ambiguous.
    assert detect_expression_key("давай") is None
    assert detect_expression_key("хочу фото") is None
    assert detect_expression_key("хочу спать") is None
    # But "давай уже" / "хочу тебя" are explicit enough.
    assert detect_expression_key("давай уже быстрее") == "upset"


def test_plain_photo_request_is_neutral_not_upset():
    # A normal "send a photo" is NOT rude — it must not trigger upset.
    assert detect_expression_key("пришли фото") is None
    assert detect_expression_key("покажи фотку") is None


def test_neutral_message_returns_none():
    assert detect_expression_key("привет") is None
    assert detect_expression_key("как дела?") is None
    assert detect_expression_key("") is None
    assert detect_expression_key(None) is None


def test_unknown_key_falls_back_to_neutral():
    desc = expression_description("does_not_exist", "Мария")
    assert "EXPRESSION:" in desc
    assert "natural warm relaxed expression" in desc


def test_known_key_produces_character_named_expression():
    desc = expression_description("upset", "Мария")
    assert desc.startswith("EXPRESSION: Мария has")
    assert "disappointed" in desc


def test_photo_request_carries_expression_key():
    # The field exists, defaults to None, and survives round-trip.
    req = PhotoRequest(scene="selfie", expression_key="smile")
    assert req.expression_key == "smile"
    assert PhotoRequest(scene="selfie").expression_key is None
