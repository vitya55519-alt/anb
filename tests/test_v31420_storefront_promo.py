"""V3.142.0: owner's storefront refresh (Nov 12) — animated welcome banner,
avatar assets for BotFather, the new display name and promo descriptions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_welcome_gif_asset_exists():
    p = ROOT / 'data' / 'media' / 'welcome_banner.gif'
    assert p.exists() and p.stat().st_size > 100_000


def test_avatar_assets_exist():
    gif = ROOT / 'data' / 'media' / 'bot_avatar.gif'
    jpg = ROOT / 'data' / 'media' / 'bot_avatar.jpg'
    mp4 = ROOT / 'data' / 'media' / 'bot_avatar.mp4'
    assert gif.exists() and gif.stat().st_size > 100_000
    assert jpg.exists() and jpg.stat().st_size > 10_000
    assert mp4.exists() and mp4.stat().st_size > 10_000


def test_avatar_applied_from_code():
    assert 'setMyProfilePhoto' in MAIN
    assert "'type': 'animated', 'animation': 'attach://avatar'" in MAIN
    assert '_spawn_background(_apply_bot_avatar())' in MAIN


def test_gif_leads_the_welcome_in_every_language():
    fn = MAIN[MAIN.index('def _welcome_banner_file('):MAIN.index('_welcome_gif_file_id = ')]
    assert fn.index('WELCOME_BANNER_GIF_PATH.exists()') < fn.index('WELCOME_BANNER_EN_PATH.exists()')


def test_gif_file_id_is_cached():
    assert "DialogStore('welcome_gif_file_id')" in MAIN
    assert '_welcome_gif_file_id[0] = msg.animation.file_id' in MAIN


def test_owner_name_is_the_code_default():
    assert "'ИИ Анна | Чат 18+ 🔞'" in MAIN
    assert 'AI Anna | 18+ Chat 🔞' in MAIN
    assert 'os.getenv(var, _BOT_NAME_FALLBACK[code])' in MAIN