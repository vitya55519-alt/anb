"""V3.21.0 static pins: couple-layer UI pack.

Eight relationship levels (7-8 premium-only plateau) with emotional names,
first-row discovery buttons (video / circle / daily quest), hearts progress
in the profile, pet name ceremony, couple album, anniversaries, one-time
onboarding tour and the rituals opt-out.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
ENGINE = (ROOT / 'services' / 'relationship_engine.py').read_text(encoding='utf-8')
COUPLE = (ROOT / 'services' / 'couple_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
SCHEDULER = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
GAMIF = (ROOT / 'services' / 'gamification_service.py').read_text(encoding='utf-8')
APARTMENT = (ROOT / 'services' / 'apartment_service.py').read_text(encoding='utf-8')
DATES = (ROOT / 'services' / 'dates_service.py').read_text(encoding='utf-8')
TESTMODE = (ROOT / 'services' / 'test_mode.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.21.0', '3.22.0', '3.23.0', '3.24.0', '3.25.0')


def test_eight_levels_with_emotional_names():
    names = MAIN[MAIN.index('RELATIONSHIP_LEVEL_NAMES = {'):MAIN.index('MAX_RELATIONSHIP_LEVEL')]
    for fragment in ('Знакомство', 'Симпатия', 'Флирт', 'Влюблённость',
                     'Любовники', 'Наша история', 'Родственные души', 'Одно целое'):
        assert fragment in names
    assert 'MAX_RELATIONSHIP_LEVEL = len(RELATIONSHIP_LEVEL_NAMES)' in MAIN


def test_engine_premium_plateau_stages():
    assert '"devoted"' in ENGINE and '"soulmate"' in ENGINE
    assert 'def set_premium_checker(fn):' in ENGINE
    # apply_delta clamps non-premium users below the plateau.
    assert "STAGE_ORDER.index(new_stage) > STAGE_ORDER.index('committed')" in ENGINE
    assert '_premium_checker(user_id)' in ENGINE


def test_premium_checker_registered_with_internal_uid_translation():
    assert 'set_premium_checker(_premium_by_internal_uid)' in MAIN
    checker = MAIN[MAIN.index('def _premium_by_internal_uid'):MAIN.index('set_premium_checker(_premium_by_internal_uid)')]
    assert 'session.get(User, uid)' in checker
    assert 'is_premium(int(user.telegram_id))' in checker


def test_main_menu_has_discovery_buttons():
    # V3.22.0: labels live in services/ui_lang.py as (ru, en) pairs and the
    # keyboard is built from MAIN_KB_ROWS via kb_label(user_lang(telegram_id)).
    from services.ui_lang import KB_LABELS, MAIN_KB_ROWS
    row_keys = {key for row in MAIN_KB_ROWS for key in row}
    for key in ('video', 'circle', 'quest', 'date',
                'apartment', 'gift', 'profile', 'premium'):
        assert key in KB_LABELS and key in row_keys
    kb = MAIN[MAIN.index('def main_keyboard('):MAIN.index('def onboarding_character_keyboard()')]
    assert 'MAIN_KB_ROWS' in kb and 'kb_label(' in kb
    # Discovery buttons register before the generic text catch-all.
    assert MAIN.index("kb_pair('circle')") < MAIN.index('@dp.message(F.text)\n')
    assert MAIN.index("kb_pair('quest')") < MAIN.index('@dp.message(F.text)\n')


def test_video_and_circle_buttons_route_to_existing_flows():
    video = MAIN[MAIN.index('async def video_button('):MAIN.index('async def circle_button(')]
    assert "callback_data='video:animate_last'" in video
    assert "callback_data='video:circle'" in video
    circle = MAIN[MAIN.index('async def circle_button('):MAIN.index('async def daily_quest_button(')]
    assert "callback_data='video:circle'" in circle


def test_daily_quest_flow():
    assert 'DAILY_QUESTS' in COUPLE
    assert 'def daily_quest(telegram_id: int)' in COUPLE
    assert 'def claim_daily_quest(telegram_id: int)' in COUPLE
    assert "attention_points = (user.attention_points or 0) + 5" in COUPLE
    handler = MAIN[MAIN.index('async def daily_quest_button('):MAIN.index('@dp.callback_query(F.data == \'questday:claim\')')]
    assert 'couple_service.daily_quest(' in handler
    assert "callback_data='questday:claim'" in handler
    claim = MAIN[MAIN.index('async def daily_quest_claim('):MAIN.index('@dp.callback_query(F.data == \'toggle:rituals\')')]
    assert 'claim_daily_quest(' in claim


def test_pet_name_ceremony_and_context():
    assert 'PET_NAMES' in COUPLE
    assert 'def assign_pet_name(telegram_id: int)' in COUPLE
    ceremony = MAIN[MAIN.index('async def _on_relationship_stage_up('):MAIN.index('set_stage_change_notifier(_on_relationship_stage_up)')]
    assert 'couple_service.assign_pet_name(telegram_id)' in ceremony
    assert 'if level == 3:' in ceremony
    assert 'if level >= 7:' in ceremony
    # She uses the pet name in conversation context.
    rel_service = (ROOT / 'services' / 'relationship_service.py').read_text(encoding='utf-8')
    assert 'user.pet_name' in rel_service


def test_couple_album():
    assert 'class CoupleAlbum(Base):' in MODELS
    assert 'def add_album_milestone(' in COUPLE
    assert 'def album_entries(' in COUPLE
    hook = MAIN[MAIN.index('async def _run_photo_background('):MAIN.index('async def _start_photo_background(')]
    assert 'couple_service.add_album_milestone(' in hook
    assert 'get_latest_photo_delivery(telegram_id)' in hook


def test_anniversaries():
    assert 'ANNIVERSARY_DAYS = (7, 30, 90)' in COUPLE
    assert 'def check_anniversary(' in COUPLE
    for key in ('anniv_7', 'anniv_30', 'anniv_90'):
        assert f"'{key}'" in GAMIF
    hook = MAIN[MAIN.index('async def text_message('):MAIN.index('idea_edit = _photo_idea_edit_sessions')]
    assert 'couple_service.check_anniversary(' in hook
    assert "'anniversary_celebrated'" in hook
    assert '_anniversary_push' in hook


def test_profile_hearts_progress_and_plateau_hint():
    block = MAIN[MAIN.index('async def profile_button('):MAIN.index('@dp.message(F.text.in_(kb_pair(\'alarm\')))')]
    assert "hearts = '❤️' * min(level, MAX_RELATIONSHIP_LEVEL)" in block
    assert "🤍" in block
    assert 'уровень {level}/{MAX_RELATIONSHIP_LEVEL}' in block
    assert 'Родственные души' in block  # plateau hint text
    assert 'couple_service.album_entries(uid)' in block
    assert 'couple_service.get_pet_name(' in block


def test_onboarding_tour():
    block = MAIN[MAIN.index('async def onboarding_character_select('):MAIN.index("@dp.callback_query(F.data == 'onboard:meet')")]
    assert 'tour_done' in block
    assert 'быстрый тур по кнопкам' in block
    assert "'onboarding_tour_sent'" in block


def test_rituals_opt_out():
    assert 'notify_rituals' in MODELS
    assert 'User.notify_rituals!=False' in SCHEDULER
    toggle = MAIN[MAIN.index("F.data == 'toggle:rituals'"):MAIN.index('# V3.19.0: per-user cooldown')]
    assert 'update_user_settings(cq.from_user.id, notify_rituals=new)' in toggle
    settings_block = MAIN[MAIN.index('@dp.message(Command(\'settings\'))'):MAIN.index('@dp.message(Command(\'profile\'))')]
    assert 'Утренние/вечерние ритуалы' in settings_block
    assert "callback_data='toggle:rituals'" in settings_block


def test_user_columns():
    for column in ('pet_name', 'quest_claimed_date', 'tour_done', 'notify_rituals', 'anniversaries'):
        assert column in MODELS


def test_premium_pitch_mentions_plateau():
    pitch = MAIN[MAIN.index('def premium_pitch_text('):MAIN.index('def _sleep_block_markup(')]
    assert 'уровни 7–8 отношений' in pitch
    assert '«Родственные души» и «Одно целое»' in pitch


def test_premium_rooms_and_dates_for_plateau():
    assert "id='candles'" in APARTMENT
    assert 'min_level=7' in APARTMENT
    assert 'min(8, level)' in APARTMENT
    assert "Date('spa'" in DATES
    assert "Date('night'" in DATES
    assert 'min(8, level)' in DATES


def test_photo_stage_index_extended():
    photo = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
    assert "'devoted': 6, 'soulmate': 7" in photo


def test_test_mode_covers_all_stages():
    assert '"devoted"' in TESTMODE and '"soulmate"' in TESTMODE
    assert '8 · Одно целое' in TESTMODE
