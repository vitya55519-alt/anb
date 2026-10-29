"""V3.93.0: one ready-made free chat photo a day without Premium, two with it."""
from pathlib import Path

import config
from services import chat_photo_allowance as cpa

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_tiers():
    assert config.CHAT_FREE_PHOTOS_PER_DAY == 1
    assert config.CHAT_PREMIUM_PHOTOS_PER_DAY == 2
    assert cpa.daily_free_photos(False) == 1 and cpa.daily_free_photos(True) == 2


def test_spicy_prompts_are_never_reused():
    for p in ('пришли голую', 'в белье', 'покажи сиськи', 'nude pls'):
        assert cpa._SPICY_PROMPT.search(p), p
    for p in ('покажи себя', 'пришли селфи', 'что делаешь?'):
        assert not cpa._SPICY_PROMPT.search(p), p


def test_gates_wired():
    assert "return 'free_used'" in MAIN
    assert "CHAT_PHOTO_BLOCK_TEXT['free_used']" in MAIN  # bot chat
    assert 'reused_photo(character_id, uid)' in MAIN  # app chat
    assert "kind == 'photo' and telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id)" in MAIN
    html = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    assert "j.photo_block === 'free_used'" in html
