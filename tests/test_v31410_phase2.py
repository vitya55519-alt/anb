"""V3.141.0: owner ТЗ (Фаза 2) — три задачи.

1. Onboarding: на 5-м (запасной 7-м) сообщении первого диалога нового
   non-Premium юзера скрипт перехватывает LLM: заготовленный текст + одно
   незаблюренное селфи из заранее сохранённых (file_id витрины / референс),
   без генерации и без списаний. Один раз на юзера.
2. Воронка [INVITE_FRIEND] в безлимитном чате: интеграционный тест reply()
   с мок-LLM — тег вырезан до истории, стейт переключён на duo, тизер помечен.
   В duo девушки периодически предлагают совместное фото (платное).
3. ROI по src_tag в админке: [оплаты юзеров с меткой] − [их LLM + картинки]
   = чистая прибыль источника; затраты атрибутируются по telegram_id.
"""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from config import ROI_USD_RUB
from models.app_models import ImageSpend, LlmUsage, StarTransaction, User, utcnow
from services.db import SessionLocal, init_db
from services.character_card_service import ensure_default_cards
from services.user_service import ensure_user
from services.memory_service import save_message, get_recent_messages
from services import onboarding_demo as demo
from services import invite_funnel as funnel
from services import chat_guest_service as cgs
from services import spend_service
from services.ui_lang import FLOW_TEXT, flow_text

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
CUSTOM = (ROOT / 'services' / 'custom_character_service.py').read_text(encoding='utf-8')


def setup_module(_):
    init_db()
    ensure_default_cards()


def _history(n_user: int):
    return [SimpleNamespace(role='user', content=f'привет {i}') for i in range(n_user)]


# ── Задача 1: onboarding-демо ──────────────────────────────────────────────

def test_demo_text_exists_in_all_eight_languages():
    for lang in ('ru', 'en', 'es', 'it', 'fr', 'zh', 'ja', 'bn'):
        assert 'onboarding_demo' in FLOW_TEXT[lang], lang
        assert FLOW_TEXT[lang]['onboarding_demo'].strip()
    ru = flow_text('ru', 'onboarding_demo')
    assert 'понравился' in ru and 'лови фото' in ru
    # the hook rule applies to the scripted line too
    assert ru.rstrip().endswith(('?', '😏'))


def test_intercept_fires_on_the_fifth_message_exactly_once():
    tid = 555001
    uid = ensure_user(tid, 'demo5')
    text = demo.maybe_intercept(tid, uid, 'anna_01', 'пятый', _history(4), False, 'ru')
    assert text == flow_text('ru', 'onboarding_demo')
    # both messages landed in the shared history
    roles = [(m.role, m.content) for m in get_recent_messages(uid, 'anna_01', 10)]
    assert ('user', 'пятый') in roles
    assert ('assistant', text) in roles
    # the photo mark is one-shot
    assert demo.take_pending(tid, 'anna_01') is True
    assert demo.take_pending(tid, 'anna_01') is False
    # never again for this user, even on the 7th
    assert demo.maybe_intercept(tid, uid, 'anna_01', 'седьмой', _history(6), False, 'ru') is None


def test_seventh_message_is_the_fallback():
    tid = 555002
    uid = ensure_user(tid, 'demo7')
    assert demo.maybe_intercept(tid, uid, 'anna_01', 'x', _history(5), False, 'ru') is None
    text = demo.maybe_intercept(tid, uid, 'anna_01', 'седьмой', _history(6), False, 'ru')
    assert text == flow_text('ru', 'onboarding_demo')
    assert demo.take_pending(tid, 'anna_01') is True


def test_intercept_skips_premium_duo_and_early_messages():
    tid = 555003
    uid = ensure_user(tid, 'demoSkip')
    assert demo.maybe_intercept(tid, uid, 'anna_01', 'x', _history(4), True, 'ru') is None
    assert demo.maybe_intercept(tid, uid, 'anna_01', 'x', _history(3), False, 'ru') is None
    cgs.set_guest(tid, 'anna_01', 'alisa_01')
    try:
        assert demo.maybe_intercept(tid, uid, 'anna_01', 'x', _history(4), False, 'ru') is None
    finally:
        cgs.set_guest(tid, 'anna_01', None)


def test_demo_photo_is_presaved_not_generated():
    # no override in the test DB → the canonical face URL, never a render
    assert demo.photo_url_for('anna_01') == '/webapp/photo/anna_01?i=0'
    src = (ROOT / 'services' / 'onboarding_demo.py').read_text(encoding='utf-8')
    assert 'card_photo_file_id' in src
    assert 'generate_photo' not in src and 'generate_private' not in src


def test_reply_intercepts_before_the_llm(monkeypatch):
    import services.chat_service as cs
    tid = 555004
    uid = ensure_user(tid, 'demoReply', language_code='ru')
    for i in range(4):
        save_message(uid, 'anna_01', 'user', f'привет {i}')
    calls = []

    class R:
        text = 'обычный ответ модели'
        provider = 'test'
        complete = True

    async def fake(messages, **kw):
        calls.append(kw.get('purpose'))
        return R()

    monkeypatch.setattr(cs, 'generate_text', fake)
    answer = asyncio.run(cs.reply(tid, 'demoReply', 'пятое сообщение', language_code='ru'))
    assert answer == flow_text('ru', 'onboarding_demo')
    assert 'dialogue' not in calls  # the LLM never spoke
    assert demo.take_pending(tid, 'anna_01') is True


def test_delivery_wiring_bot_and_app():
    assert 'onboarding_demo.maybe_intercept' in CHAT
    wrapper = MAIN[MAIN.index('async def send_answer('):MAIN.index('async def _send_answer_body(')]
    assert 'onboarding_demo.take_pending' in wrapper
    assert 'send_bot_photo' in wrapper
    turn = MAIN[MAIN.index('async def _webapp_chat_turn('):]
    turn = turn[:turn.index('\nasync def ')]
    # the demo is consumed BEFORE the paid PHOTO_PROMISE branch can fire
    assert turn.index('onboarding_demo.take_pending') < turn.index('PHOTO_PROMISE.search')
    assert "'photo_url': demo_url" in turn


# ── Задача 2: воронка [INVITE_FRIEND] в безлимитном чате ───────────────────

def test_reply_funnel_end_to_end_with_mock_llm(monkeypatch):
    import services.chat_service as cs
    tid = 555010
    uid = ensure_user(tid, 'funnel', language_code='ru')
    # 5 saved messages → the current one is the 6th: no onboarding intercept,
    # and enough history for the upsell cooldown gate.
    for i in range(5):
        save_message(uid, 'anna_01', 'user', f'привет {i}')
    expected_guest = funnel.pick_guest(tid, 'anna_01')
    assert expected_guest  # there is a friend to invite

    class R:
        text = 'давай позовём её, будет веселее [INVITE_FRIEND]'
        provider = 'test'
        complete = True

    async def fake(messages, **kw):
        return R()

    monkeypatch.setattr(cs, 'generate_text', fake)
    answer = asyncio.run(cs.reply(tid, 'funnel', 'давай позовём подругу', language_code='ru'))
    # the tag never reaches the user nor the history
    assert '[INVITE_FRIEND]' not in answer
    assert cgs.get_guest(tid, 'anna_01') == expected_guest
    assert funnel.take_pending(tid, 'anna_01') == expected_guest
    assert funnel.take_pending(tid, 'anna_01') == ''
    saved = [m.content for m in get_recent_messages(uid, 'anna_01', 6) if m.role == 'assistant']
    assert saved and all('[INVITE_FRIEND]' not in c for c in saved)
    cgs.set_guest(tid, 'anna_01', None)


def test_duo_prompts_sell_the_joint_photo():
    from services.character_service import build_system_prompt, get_character
    duo = cgs.guest_prompt('Анна', 'alisa_01')
    assert 'JOINT PHOTO UPSELL' in duo
    assert 'once every 10-15 messages' in duo
    assert 'paid feature' in duo
    block = CUSTOM[CUSTOM.index('В ЭТОМ ЧАТЕ ВАС ДВЕ'):]
    assert 'JOINT_PHOTO_RULE' in block[:1000]
    solo = build_system_prompt(get_character('anna_01'), 'REL', [], character_id='anna_01')
    assert 'JOINT PHOTO UPSELL' not in solo


# ── Задача 3: ROI по источникам ────────────────────────────────────────────

def test_spend_ledgers_carry_the_user():
    assert 'telegram_id' in LlmUsage.__table__.columns
    assert 'telegram_id' in ImageSpend.__table__.columns
    spend_service.set_spend_user(555020)
    spend_service.record_llm_usage('dialogue', 'openrouter', 'm', cost_usd=0.001)
    spend_service.record_image_spend('gemini_image', 'selfie', 0.002)
    with SessionLocal() as s:
        llm = s.scalars(select(LlmUsage).order_by(LlmUsage.id.desc())).first()
        img = s.scalars(select(ImageSpend).order_by(ImageSpend.id.desc())).first()
        assert llm.telegram_id == 555020
        assert img.telegram_id == 555020
    spend_service.set_spend_user(None)
    spend_service.record_llm_usage('dialogue', 'openrouter', 'm', cost_usd=0.001)
    with SessionLocal() as s:
        llm = s.scalars(select(LlmUsage).order_by(LlmUsage.id.desc())).first()
        assert llm.telegram_id == 0


def test_source_roi_is_revenue_minus_api_cost():
    from services import analytics_service as an
    from services.partner_service import payment_rub_value
    tid_plus, tid_minus = 555101, 555102
    uid_plus = ensure_user(tid_plus, 'roi+')
    uid_minus = ensure_user(tid_minus, 'roi-')
    with SessionLocal() as s:
        s.get(User, uid_plus).source_tag = 'roi_plus_x'
        s.get(User, uid_minus).source_tag = 'roi_minus_x'
        s.add(StarTransaction(user_id=uid_plus, transaction_type='purchase',
                              product='premium_month', stars=250,
                              telegram_charge_id='roi-test-plus-1', provider='stars'))
        s.add(LlmUsage(day=utcnow().date(), purpose='dialogue', provider='openrouter',
                       model='m', cost_usd=0.10, telegram_id=tid_plus))
        s.add(ImageSpend(day=utcnow().date(), engine='gemini_image', scene='selfie',
                         cost_usd=0.10, telegram_id=tid_minus))
        s.add(LlmUsage(day=utcnow().date(), purpose='dialogue', provider='openrouter',
                       model='m', cost_usd=0.05, telegram_id=0))
        s.commit()
    roi = an.source_roi(30)
    rows = {r['tag']: r for r in roi['rows']}
    rev = payment_rub_value('premium_month', 250, 'stars', None)
    assert rev > 0
    assert rows['roi_plus_x']['revenue_rub'] == round(rev, 2)
    assert rows['roi_plus_x']['cost_rub'] == round(0.10 * ROI_USD_RUB, 2)
    assert rows['roi_plus_x']['profit_rub'] == round(rev - 0.10 * ROI_USD_RUB, 2)
    assert rows['roi_plus_x']['payers'] == 1
    # the losing source: no revenue, pure API fire
    assert rows['roi_minus_x']['revenue_rub'] == 0.0
    assert rows['roi_minus_x']['profit_rub'] == round(-0.10 * ROI_USD_RUB, 2)
    assert roi['unattributed_rub'] >= round(0.05 * ROI_USD_RUB, 2)
    profits = [r['profit_rub'] for r in roi['rows']]
    assert profits == sorted(profits, reverse=True)


def test_admin_roi_screen_and_attribution_wiring():
    assert "callback_data='admin:roi'" in MAIN
    assert 'analytics_service.source_roi' in MAIN
    assert 'ROI_USD_RUB' in (ROOT / 'config.py').read_text(encoding='utf-8')
    assert 'spend_service.set_spend_user(user_id)' in CHAT
    assert 'spend_service.set_spend_user(telegram_id)' in MAIN
    photo = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
    assert 'spend_service.set_spend_user(telegram_id)' in photo