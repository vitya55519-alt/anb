"""Static regression tests for v3.40.0: the Come Closer main menu, admin
user-statistics + per-provider failure counters, storefront view badges and
the living animated card tiles.

Owner requests this round:
1. «счетчик отказов» — which media engine is flaky, visible in the admin;
2. «статистика пользователей для админа» — a real user-statistics screen;
3. «вверху карточки счетчик просмотров» — the «👁 427k» badge from the
   Come Closer storefront screenshot;
4. «вместо фото гифки» — animated looping previews on every built-in card;
5. «замени наше меню кнопочки на пример с первого фото» — the main reply
   keyboard becomes the Come Closer funnel (app / credits / paint / pair).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
UI_LANG = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
ANALYTICS = (ROOT / 'services' / 'analytics_service.py').read_text(encoding='utf-8')
PROV = (ROOT / 'services' / 'provider_stats_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.43.6', '3.43.5', '3.43.4', '3.43.3', '3.43.2', '3.43.1', '3.43.0', '3.42.2', '3.42.1', '3.42.0', '3.41.0', '3.40.0',)


# ── 1. main reply keyboard like the Come Closer menu ───────────────────────

def test_main_menu_is_the_come_closer_layout():
    rows = UI_LANG[UI_LANG.index('MAIN_KB_ROWS = ['):UI_LANG.index('LEVEL_NAMES_EN')]
    assert "['app']," in rows
    assert "['credits']," in rows
    assert "['paint']," in rows
    # V3.42.0: partner is its own full-width row; support sits with the legal row
    assert "['partner']," in rows
    assert "['support', 'legal']," in rows
    # the «open app» row is a real web_app tile — the teal direct launch
    kb = MAIN[MAIN.index('def main_keyboard('):MAIN.index('def _character_pick_buttons(')]
    assert "web_app=types.WebAppInfo(url=f'{PUBLIC_BASE_URL}/webapp')" in kb


# ── 2. provider failure counters ───────────────────────────────────────────

def test_provider_counters_service_and_hooks():
    assert '__tablename__ = "provider_stats"' in MODELS
    assert 'def record_provider(provider: str, ok: bool, error: str | None = None)' in PROV
    assert 'def provider_snapshot()' in PROV
    # every engine leg of the photo chain bumps its counter
    for name in ('photo/seedream_edit', 'photo/seedream_t2i', 'photo/gemini'):
        assert f"record_provider('{name}', True)" in PHOTO
        assert f"record_provider('{name}', False," in PHOTO
    # the video / circle chains (bot dialog + Mini App) bump per engine
    assert "record_provider(f'video/{engine_name}', True)" in MAIN
    assert "record_provider(f'circle/{engine_name}', False," in MAIN
    assert "record_provider(f'circle/{ename}', True)" in MAIN


def test_admin_providers_screen():
    assert "InlineKeyboardButton(text='🩺 Отказы', callback_data='admin:providers')" in MAIN
    assert "@dp.callback_query(F.data == 'admin:providers')" in MAIN
    assert '🩺 Отказы провайдеров' in MAIN


# ── 3. user statistics for the admin ───────────────────────────────────────

def test_admin_stats_screen_is_user_statistics():
    assert "'new_24h':" in ANALYTICS
    assert "'premium_active':" in ANALYTICS
    assert "'top_characters':" in ANALYTICS
    assert "Subscription.status == 'active'" in ANALYTICS
    assert '📊 Статистика пользователей' in MAIN
    assert '🏆 топ персонажей (7д):' in MAIN
    assert '⭐ Premium активен:' in MAIN
    assert '🎨 студия: ✅' in MAIN


# ── 4. storefront view counter ─────────────────────────────────────────────

def test_view_counter_end_to_end():
    assert '__tablename__ = "character_stats"' in MODELS
    assert 'def bump_character_views(character_id: str) -> int' in WEBAPP_SVC
    assert 'def character_views_map()' in WEBAPP_SVC
    assert "'views': views.get(card.character_id, 0)," in WEBAPP_SVC
    assert "add_post('/webapp/api/char_view', _webapp_api_char_view)" in MAIN
    assert 'webapp_service.bump_character_views(character_id)' in MAIN
    # frontend: the «👁 427k» pill + the fire-and-forget bump on page open
    assert '.card .views {' in INDEX
    assert 'function fmtK(n)' in INDEX
    assert 'const viewsBadge = c.views ?' in INDEX
    assert "fetch('/webapp/api/char_view?init_data='" in INDEX


# ── 5. living card tiles (animated previews) ───────────────────────────────

def test_cards_ride_animated_previews():
    for folder in ('anna', 'emily', 'maria', 'erika', 'sonya', 'vika', 'alisa', 'mila'):
        tile = ROOT / 'data' / 'references' / folder / 'card_preview.webp'
        assert tile.exists() and tile.stat().st_size > 50_000, folder
    assert 'def character_card_gif(character_id: str) -> Path | None' in WEBAPP_SVC
    assert "'card': (f'/webapp/card/{card.character_id}?v={ver}'" in WEBAPP_SVC
    assert "add_get('/webapp/gif/{character_id}', _webapp_gif)" in MAIN
    assert "content_type = 'image/webp' if gif.suffix.lower() == '.webp' else 'image/gif'" in MAIN
    assert 'img src="${esc(c.card || c.photo)}"' in INDEX
