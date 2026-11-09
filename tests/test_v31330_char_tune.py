"""V3.133.0 — «🎛 Настрой её сам»: Premium sets level + bond on her page."""
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_tune_button_on_her_page():
    assert 'id="charTune"' in HTML
    assert HTML.index('id="charTune"') > HTML.index('id="charPathBar"')
    assert 'openCharTune(c)' in HTML


def test_tune_uses_premium_pick_endpoint_and_locks_for_free():
    body = HTML.split('async function openCharTune(c) {', 1)[1].split('\nfunction ', 1)[0]
    assert '/webapp/api/chat/level/pick' in body
    assert "lv >= 4 ? br : ''" in body          # bond only from level 4
    assert "quickBuy('spicy')" in body          # free users get Premium/trial offer
    assert "' locked'" in body


def test_strings_ru_en():
    assert "tune_title: '🎛 Настрой её сам'" in HTML and "tune_title: '🎛 Set her up yourself'" in HTML
