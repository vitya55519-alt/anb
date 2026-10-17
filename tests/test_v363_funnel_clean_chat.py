"""V3.63.2: sales funnel + clean chat.

Owner data that drove it (admin panel, Oct 2026): 185 /start → 147 18+ →
78 wrote; only 9 users ever SAW a paid offer in 30 days; proactive reply rate
1/21. Owner benchmark: Come Closer (pinned main menu, menu screens replace
each other, story pushes with her photo and two buttons).
"""
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
HYG = (ROOT / 'services' / 'chat_hygiene.py').read_text(encoding='utf-8')
OFFER = (ROOT / 'services' / 'first_offer_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _load_story_hooks():
    store = types.ModuleType('services.dialog_store')

    class _Store(dict):
        def __init__(self, *a, **k):
            super().__init__()
    store.DialogStore = _Store
    pkg = sys.modules.get('services') or types.ModuleType('services')
    saved = {k: sys.modules.get(k) for k in ('services', 'services.dialog_store')}
    sys.modules['services'] = pkg
    sys.modules['services.dialog_store'] = store
    pkg.dialog_store = store
    try:
        spec = importlib.util.spec_from_file_location('story_hooks_t', ROOT / 'services' / 'story_hooks.py')
        mod = importlib.util.module_from_spec(spec)
        sys.modules['story_hooks_t'] = mod  # dataclasses resolve annotations via sys.modules
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


# ── clean chat ──────────────────────────────────────────────────────────────
def test_screen_capture_installed_on_the_bot_session():
    assert 'chat_hygiene.install(bot)' in MAIN
    assert 'bot.session.middleware(ScreenCaptureMiddleware())' in HYG


def test_menu_buttons_are_screens():
    for fn in ('start', 'app_button', 'credits_button', 'paint_button', 'partner_button',
               'support_button', 'legal_button', 'premium_button', 'profile_button',
               'settings_button', 'characters_button', 'referral_button'):
        assert f'@service_screen\nasync def {fn}(' in MAIN, fn


def test_background_tasks_cannot_join_a_closed_screen():
    # photos spawned from a menu handler must never be swept as a «screen»
    assert 'if cap is None or cap.closed:' in HYG
    assert 'cap.closed = True' in HYG


def test_main_menu_is_pinned_and_kept_out_of_the_sweep():
    assert 'await _pin_main_menu(message.chat.id, menu_msg.message_id)' in MAIN
    assert 'chat_hygiene.forget_screen(chat_id, message_id)' in MAIN
    # the menu is pinned while /start's own capture is still open
    assert 'if cap is not None and cap.chat_id == chat_id and message_id in cap.ids:' in HYG
    assert 'await bot.unpin_all_chat_messages(chat_id)' in HYG
    assert 'disable_notification=True' in HYG


def test_consent_banner_removed_and_menu_pinned_after_18plus():
    i = MAIN.index('async def consent_accept(')
    body = MAIN[i:i + 4000]
    assert 'await cq.message.delete()' in body
    assert 'await _send_pinned_menu(cq.message.chat.id, lang)' in body


def test_app_redirect_hint_replaces_itself_and_opens_her_chat():
    i = MAIN.index('if BOT_CHAT_REDIRECT and PUBLIC_BASE_URL and message.from_user.id not in _redirect_bypass:')
    body = MAIN[i:i + 1800]
    assert 'chat_hygiene.open_screen(bot, message.chat.id)' in body
    assert "/webapp?open=chat" in body
    # the old hint re-sent the whole reply keyboard every time
    assert 'reply_markup=main_keyboard(' not in body


def test_first_hello_carries_the_reply_button():
    i = MAIN.index('greeting = _first_hello(')
    body = MAIN[i:i + 1200]
    assert '/webapp?open=chat' in body
    assert 'reply_markup=hello_kb' in body
    # the one-tap first answers (V3.62.7) stay and are answered by her in the bot
    assert 'hello_kb = _first_hello_keyboard(lang)' in body
    assert '_redirect_bypass.add(cq.from_user.id)' in MAIN


def test_webapp_deep_opens_selected_chat():
    assert "get('open') !== 'chat'" in INDEX
    assert 'maybeDeepOpenChat(j.characters);' in INDEX


# ── first-evening offer ─────────────────────────────────────────────────────
def test_first_offer_scheduled_and_deduped_before_send():
    assert "scheduler.add_job(_first_offer,'interval',minutes=10" in SCHED
    i = SCHED.index('async def _first_offer(bot):')
    body = SCHED[i:i + 3000]
    assert body.index('fos.mark_offered(telegram_id)') < body.index('await bot.send_photo(')
    assert 'is_premium(telegram_id)' in body and 'has_accepted(telegram_id)' in body
    assert 'ADMIN_TELEGRAM_IDS' in body


def test_first_offer_opens_premium_with_discount_and_counts_as_paywall_view():
    i = MAIN.index("@dp.callback_query(F.data == 'first_offer:open')")
    body = MAIN[i:i + 1500]
    assert 'offer_discount(cq.from_user.id)' in body
    assert "'source': 'first_offer'" in body
    assert 'premium_keyboard(discount_info(' in body


def test_offer_card_skips_label_without_cyrillic_font():
    assert 'if font is not None and label:' in OFFER


def test_offer_cover_in_repo_is_pre_blurred_only():
    # the repository is public: only an already-blurred cover lives in it
    files = sorted((ROOT / 'data' / 'media' / 'offer').glob('*'))
    assert [f.name for f in files] == ['cover.jpg']


def test_new_user_window_shrunk():
    assert 'NEW_USER_UNLIMITED_HOURS = max(0, int(os.getenv("NEW_USER_UNLIMITED_HOURS", "3")))' in CONFIG
    assert 'Первые 24 часа после регистрации' not in INDEX


# ── story hooks ─────────────────────────────────────────────────────────────
def test_story_hooks_wired_into_day1_and_miss_push():
    assert 'if await _send_story(bot,uid,telegram_id,_char):' in SCHED
    assert "if kind=='miss' and await _send_story(bot,uid,telegram_id,char_id):" in SCHED
    assert "@dp.callback_query(F.data.startswith('story:'))" in MAIN


def test_story_photo_never_borrowed_from_another_story():
    assert "_media_pick('stories',story.key,exact=True) or _reference_photo(char_id)" in SCHED


def test_story_hooks_each_once_per_user():
    sh = _load_story_hooks()
    seen = set()
    for _ in range(len(sh.STORIES)):
        story = sh.pick_unused(42)
        assert story is not None and story.key not in seen
        seen.add(story.key)
        sh.mark_used(42, story.key)
    assert sh.pick_unused(42) is None


def test_story_choices_have_both_languages_and_short_labels():
    sh = _load_story_hooks()
    for story in sh.STORIES:
        for c in (story.a, story.b):
            assert c.label_ru and c.label_en and c.reply_ru and c.reply_en
            # callback data: «story:<key>:<a|b>» stays far under Telegram's 64 bytes
            assert len(f'story:{story.key}:a'.encode()) <= 64
        assert sh.choice(story, 'a') is story.a and sh.choice(story, 'x') is None


# ── owner push photos (kept as Telegram file_ids, never in the public repo) ─
def _load_push_photos():
    store = types.ModuleType('services.dialog_store')

    class _Store(dict):
        def __init__(self, *a, **k):
            super().__init__()
    store.DialogStore = _Store
    pkg = types.ModuleType('services')
    pkg.dialog_store = store
    saved = {k: sys.modules.get(k) for k in ('services', 'services.dialog_store')}
    sys.modules['services'] = pkg
    sys.modules['services.dialog_store'] = store
    try:
        spec = importlib.util.spec_from_file_location('push_photos_t', ROOT / 'services' / 'push_photos.py')
        mod = importlib.util.module_from_spec(spec)
        sys.modules['push_photos_t'] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_push_photos_resolve_names_and_store_per_girl():
    pp = _load_push_photos()

    class Card:
        def __init__(self, cid, name):
            self.character_id, self.display_name = cid, name
    cards = [Card('anna_01', 'Анна'), Card('vika_01', 'Вика')]
    assert pp.resolve_character('Вика', cards) == 'vika_01'
    assert pp.resolve_character('vika', cards) == 'vika_01'
    assert pp.resolve_character('анн', cards) == 'anna_01'
    assert pp.resolve_character('кто-то', cards) is None
    assert pp.add('vika_01', 'F1') == 1 and pp.add('vika_01', 'F2') == 2
    assert pp.add('vika_01', 'F1') == 2  # no duplicates
    assert pp.pick('vika_01') in ('F1', 'F2') and pp.pick('anna_01') is None
    assert pp.counts() == {'vika_01': 2}
    assert pp.clear('vika_01') == 2 and pp.counts() == {}


def test_push_photos_wired_admin_only():
    i = MAIN.index("@dp.message(F.photo, F.caption.regexp(r'^/storyphoto\\b'))")
    body = MAIN[i:i + 1200]
    assert 'if message.from_user.id not in ADMIN_TELEGRAM_IDS:' in body
    assert 'push_photos.add(character_id, message.photo[-1].file_id)' in body
    # the catch-all photo handler is registered later, so the caption wins
    assert i < MAIN.index('@dp.message(F.photo)\n')
    assert 'push_photos.pick(char_id or CHARACTER_ID) if story.photo_ok else None' in SCHED
    assert 'source=await bot.download(fid)' in SCHED
