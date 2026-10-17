"""V3.63.11: the girls used only 😏 and 🙈 — repeats get a fresh emoji of the same mood."""
import random
from pathlib import Path

from services.dialogue_guard_service import diversify_emoji, _EMOJI_GROUP_OF

ROOT = Path(__file__).resolve().parents[1]


def test_emoji_from_her_last_messages_is_swapped_within_its_mood():
    out = diversify_emoji('ну ты даёшь 😏', ['привет 😏', 'ой 🙈'], rng=random.Random(1))
    assert '😏' not in out
    new = out.rsplit(' ', 1)[1]
    assert _EMOJI_GROUP_OF[new] is _EMOJI_GROUP_OF['😏']


def test_fresh_emoji_and_plain_text_stay():
    assert diversify_emoji('скучала 🥰', ['привет 😏']) == 'скучала 🥰'
    assert diversify_emoji('просто текст', ['😏']) == 'просто текст'


def test_same_emoji_twice_in_one_answer_is_varied():
    out = diversify_emoji('🙈 ну всё 🙈', [], rng=random.Random(3))
    assert out.count('🙈') == 1


def test_wired_into_reply_and_prompt_examples_are_varied():
    chat = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
    assert "answer = diversify_emoji(answer, [m.content for m in history if m.role == 'assistant'][-4:])" in chat
    prompt = (ROOT / 'services' / 'character_service.py').read_text(encoding='utf-8')
    assert 'а 😏 и 🙈 — редко' in prompt
    assert prompt.count('😏') <= 3
