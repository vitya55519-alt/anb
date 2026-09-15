"""Static regression tests for v3.32.0: legal pack for the payment partner.

Platega (СБП НСПК) bank approval requires, permanently accessible from the
bot: a privacy policy, a user agreement, support contacts (no groups —
ticket system/username/email), and actual prices/tariffs — plus the temporary
check word «чекап» and NO ИП/ООО/ИНН personal data anywhere in the texts.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
LEGAL = (ROOT / 'services' / 'legal_service.py').read_text(encoding='utf-8')
UI_LANG = (ROOT / 'services' / 'ui_lang.py').read_text(encoding='utf-8')
CONSENT = (ROOT / 'services' / 'consent_service.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.31.8', '3.32.0', '3.32.1', '3.33.0', '3.33.1', '3.34.0', '3.34.1')


def test_legal_service_documents_exist():
    assert 'PRIVACY_POLICY = (' in LEGAL
    assert 'USER_AGREEMENT = (' in LEGAL
    # required document sections (partner template structure, adapted)
    for section in (
        '1. Общие положения',
        '2. Сбор информации',
        '4. Передача информации третьим лицам',
        '7. Изменения в Политике',
        '8. Контакты',
    ):
        assert section in LEGAL, f'privacy policy missing section: {section}'
    for section in (
        '7. Платежи и возвраты',
        '10. Контактная информация',
        '18+',
        'chargeback',
    ):
        assert section in LEGAL, f'user agreement missing: {section}'
    # the documents are dated and identify the service
    assert "LEGAL_VERSION = '2026-09-15'" in LEGAL
    assert 'LEGAL_DATE_RU' in LEGAL
    assert "os.getenv('LEGAL_BOT_USERNAME', '@Anna67901_bot')" in LEGAL


def test_no_personal_registration_data_in_legal_texts():
    # partner's compliance rule: no ИП / ООО / ИНН / ОГРН in the user-facing
    # texts — scope to the document constants (the module docstring may name
    # the rule itself).
    texts = LEGAL[LEGAL.index('PRIVACY_POLICY = ('):]
    for marker in ('ИНН', 'ООО', 'ОГРН'):
        assert marker not in texts, f'personal data marker in legal texts: {marker}'


def test_tariffs_render_live_prices():
    assert 'def tariffs_text(lang' in LEGAL
    for constant in (
        'PREMIUM_MONTHLY_STARS',
        'PREMIUM_MONTHLY_PHOTO_CREDITS',
        'PHOTO_COST_STARS',
        'CHAT_PHOTO_OFFER_STARS',
        'CUSTOM_PHOTO_COST_STARS',
        'VIDEO_COST_STARS',
        'VIDEO_PREMIUM_FREE_DAILY',
        'GALLERY_DOWNLOAD_STARS',
        'QUEST_REPLAY_STARS',
        'CONSTRUCTOR_COST_STARS',
        'CONSTRUCTOR_COST_RUB',
        'FREE_MESSAGES_PER_DAY',
        'FREE_PHOTOS_LEVEL_1_2',
        'FREE_PHOTOS_LEVEL_3_6',
    ):
        assert constant in LEGAL, f'tariffs missing live constant: {constant}'
    # gifts range and the daily discount come from the gift catalog itself
    assert 'gifts_service.GIFTS' in LEGAL
    assert 'gifts_service.DAILY_DISCOUNT' in LEGAL


def test_support_and_menu_and_splitter():
    assert 'def support_text(lang' in LEGAL
    assert '/paysupport' in LEGAL
    assert '/delete_me' in LEGAL
    assert 'def legal_menu_text(lang' in LEGAL
    assert "LEGAL_CHECK_WORD = 'чекап'" in LEGAL
    assert 'def split_legal_text(text: str, limit: int = 3500)' in LEGAL


def test_legal_row_always_visible_in_main_keyboard():
    assert "'legal': ('📜 Документы', '📜 Documents')," in UI_LANG
    rows = UI_LANG[UI_LANG.index('MAIN_KB_ROWS = ['):UI_LANG.index('LEVEL_NAMES_EN')]
    assert "['legal']," in rows


def test_legal_button_handler_wired_before_catchall():
    assert "@dp.message(F.text.in_(kb_pair('legal')))" in MAIN
    assert 'async def legal_button(message: types.Message):' in MAIN
    # reply-button handlers must precede the generic text catch-all
    assert MAIN.index("kb_pair('legal')") < MAIN.index('@dp.message(F.text)\n')


def test_legal_inline_menu_callbacks():
    assert 'def legal_keyboard(lang: str = RU):' in MAIN
    for cb in ('legal:privacy', 'legal:terms', 'legal:tariffs', 'legal:support'):
        assert f"callback_data='{cb}'" in MAIN
        assert f"F.data == '{cb}'" in MAIN


def test_full_documents_sent_by_commands_and_consent():
    # shared splitter-backed sender
    assert 'async def _send_legal_doc(chat_id: int, text: str, lang: str = RU):' in MAIN
    assert 'legal_service.split_legal_text(full)' in MAIN
    terms = MAIN[MAIN.index("@dp.message(Command('terms'))"):MAIN.index("@dp.message(Command('support'))")]
    assert 'legal_service.USER_AGREEMENT' in terms
    assert 'legal_service.PRIVACY_POLICY' in terms
    # /start consent buttons show the full documents too
    consent = MAIN[MAIN.index("@dp.callback_query(F.data == 'consent:terms')"):]
    consent = consent[:consent.index("async def _send_onboarding_character_card")]
    assert 'legal_service.USER_AGREEMENT' in consent
    assert 'legal_service.PRIVACY_POLICY' in consent


def test_legal_command_registered():
    assert "@dp.message(Command('legal'))" in MAIN
    assert "types.BotCommand(command='legal', description='📜 Документы и цены')" in MAIN


def test_consent_versions_bumped_for_new_documents():
    assert "TERMS_VERSION = '2026-09-15'" in CONSENT
    assert "PRIVACY_VERSION = '2026-09-15'" in CONSENT
