"""Static regression tests for v3.42.2: the in-app chat action strip loses the
crooked voice button and the remaining icon-only squares become readable
labeled pills.

Owner request (voice note + screenshot of the chat strip):
1. «убери кнопочку из чата, связанную с голосом … он работает криво» — the 🎙
   voice action is removed from the chat media strip (button + click listener).
2. «там маленькие кнопочки, кривые, они непонятно для чего сделаны … человек,
   который заходит, он вообще не понимает, зачем это все» — every remaining
   action now shows a localized text label under its icon so a newcomer can
   read what it does instead of guessing from an emoji.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.42.2', '3.42.1', '3.42.0')


# ── the crooked voice button is gone ──────────────────────────────────────

def test_voice_button_and_listener_removed():
    assert 'id="mediaVoice"' not in INDEX
    assert "getElementById('mediaVoice')" not in INDEX
    assert "requestMedia('voice')" not in INDEX
    # the other media/feature actions stay wired
    assert "getElementById('mediaPhoto').addEventListener('click', () => requestMedia('photo'))" in INDEX
    assert "getElementById('mediaCircle').addEventListener('click', () => requestMedia('circle'))" in INDEX
    assert "getElementById('mediaVideo').addEventListener('click', () => requestMedia('video'))" in INDEX


# ── the strip is now readable labeled pills ───────────────────────────────

def test_action_buttons_carry_localized_labels():
    # each pill renders an icon span + a label span filled from the L dict
    for btn, lb in (('mediaPhoto', 'lbMediaPhoto'), ('mediaVideo', 'lbMediaVideo'),
                    ('mediaCircle', 'lbMediaCircle'), ('featQuest', 'lbFeatQuest'),
                    ('featDate', 'lbFeatDate'), ('featApt', 'lbFeatApt')):
        assert f'<span class="lb" id="{lb}"></span>' in INDEX, f'missing label span for {btn}'
        assert f"document.getElementById('{lb}').textContent = L." in INDEX, f'label not localized: {lb}'
    # the pill CSS stacks icon over a small text label
    assert '.chat-media button .ic {' in INDEX
    assert '.chat-media button .lb {' in INDEX
    # no more fixed 38px icon-only squares
    assert 'width: 38px; height: 38px' not in INDEX


def test_label_strings_exist_in_both_languages():
    for key_ru, key_en in ((
        "media_photo: 'Фото'", "media_photo: 'Photo'"), (
        "media_video: 'Видео'", "media_video: 'Video'"), (
        "media_circle: 'Кружок'", "media_circle: 'Circle'"), (
        "feat_quest: 'Задание'", "feat_quest: 'Quest'"), (
        "feat_date: 'Свидание'", "feat_date: 'Date'"), (
        "feat_apt: 'Квартира'", "feat_apt: 'Apartment'")):
        assert key_ru in INDEX, f'missing RU label: {key_ru}'
        assert key_en in INDEX, f'missing EN label: {key_en}'
