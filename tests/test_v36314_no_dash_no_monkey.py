"""V3.63.14: from a live chat with Vika: an em dash in every reply, 🙈 then 🙊."""
import random

from services.dialogue_guard_service import casual_punctuation, diversify_emoji


def test_em_dash_becomes_a_comma():
    assert casual_punctuation('ты уже тут — и я рада') == 'ты уже тут, и я рада'
    assert casual_punctuation('ну, — хоть всю ночь') == 'ну, хоть всю ночь'
    assert casual_punctuation('— ну привет') == '— ну привет'
    assert casual_punctuation('2–3 дня') == '2–3 дня'


def test_monkey_after_monkey_becomes_another_shy_face():
    out = diversify_emoji('пришлю кое-что 🙊 не проси', ['ой 🙈'], rng=random.Random(1))
    assert not set(out) & set('🙈🙊🙉')
    out = diversify_emoji('🙈 и 🙊', [], rng=random.Random(2))
    assert out.startswith('🙈') and '🙊' not in out
    assert diversify_emoji('ой 🙈', ['привет 😊']) == 'ой 🙈'
