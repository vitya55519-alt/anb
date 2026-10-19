from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_spicy_banner_sits_right_under_the_channel_banner():
    chan = INDEX.index('id="chanBanner"')
    spicy = INDEX.index('id="spicyBanner"')
    grid = INDEX.index('id="chargrid"')
    assert chan < spicy < grid
    assert "spicy_banner: '🔥 Пошлый режим'" in INDEX
    assert 'общение пойдёт по-другому' in INDEX


def test_banner_and_settings_share_one_switch():
    assert "rs.addEventListener('click', toggleSpicy)" in INDEX
    assert "await toggleSpicy();" in INDEX
    assert "j403.error === 'adult_confirm'" in INDEX
    assert 'renderSpicyBanner();' in INDEX


def test_enabling_still_needs_premium_and_18_plus():
    body = MAIN[MAIN.index('async def _webapp_api_spicy'):MAIN.index('async def _webapp_api_chat_history')]
    assert 'not is_premium(telegram_id)' in body
    assert 'not is_adult_confirmed(telegram_id)' in body
    assert "'error': 'adult_confirm'" in body
