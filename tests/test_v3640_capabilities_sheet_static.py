"""V3.64.0: «✨ Возможности» replaces the pill strip above the chat input.

Owner: the row Свидание/Квартира/Видео/… above the message field was confusing.
Now one full-width button opens a sheet listing every feature with a short
explanation; each row keeps its old id and click listener.
"""
from pathlib import Path

INDEX = (Path(__file__).resolve().parents[1] / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_one_button_above_input_and_strip_moved_into_sheet():
    chat_input = INDEX.split('<div class="chat-input">', 1)[1].split('<div class="chat-field">', 1)[0]
    assert 'id="featMenuBtn"' in chat_input
    assert 'chat-media' not in chat_input
    sheet = INDEX.split('id="capSheet"', 1)[1].split('</div></div>', 1)[0]
    for btn in ('mediaPhoto', 'featQuest', 'featStory', 'featDate', 'featApt', 'featVideo', 'featCosplay', 'featHot'):
        assert f'id="{btn}"' in sheet


def test_every_feature_has_an_explanation_in_both_languages():
    for key in ('cap_photo', 'cap_quest', 'cap_story', 'cap_date', 'cap_apt', 'cap_video', 'cap_cosplay', 'cap_hot', 'cap_btn'):
        assert INDEX.count(f'{key}: ') == 2, key
    assert "cap_btn: '✨ Возможности'" in INDEX


def test_sheet_opens_and_closes_on_row_tap():
    assert "getElementById('featMenuBtn').addEventListener('click', openCapSheet)" in INDEX
    assert "e.target.closest('.chat-media button')) closeCapSheet()" in INDEX
