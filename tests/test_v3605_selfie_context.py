"""V3.60.5: a plain selfie follows where she just said she is."""
from pathlib import Path

from services.photo_service import place_from_dialog

MAIN = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')


def test_in_bed_next_to_sleeping_husband_is_a_night_bed_selfie():
    place, light = place_from_dialog(['лежу рядом с мужем, он уже сопит, а я в телефоне 🙈'])
    assert 'in bed' in place and 'secretly' in place and 'late night' in light


def test_newest_message_wins_and_unknown_is_empty():
    assert 'kitchen' in place_from_dialog(['я на кухне, готовлю', 'была в душе'])[0]
    assert place_from_dialog(['привет, как ты?']) == ('', '')


def test_app_chat_selfie_uses_the_dialog_place():
    assert 'photo_req = _selfie_from_dialog(uid, character_id, photo_request)' in MAIN
    assert "data, mime, ext = await _webapp_pipeline_photo(telegram_id, character_id, photo_req)" in MAIN
