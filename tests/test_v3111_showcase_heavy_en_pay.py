"""V3.111.0 — first-hour showcase, one honest offer after 150 messages, and
English speakers can actually pay in the bot chat (Stars + crypto/card)."""
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')


def test_plan_rows_ru_and_en():
    from services import offer_buttons as ob
    ru = ob.plan_rows(True, False, platega=True)
    assert ru[0][1] == 'platega:premium_trial' and 'карта / СБП' in ru[0][0]
    assert ru[-1][1] == 'buy:premium_trial'
    en = ob.plan_rows(True, True, platega=True)
    assert en[0][1] == 'buy:premium_trial' and 'Stars' in en[0][0]
    assert en[1][1] == 'platega:premium_trial' and 'crypto' in en[1][0]
    assert not any(ch in ''.join(t for t, _ in en) for ch in 'абвгдежзийклмнопрстуфхцчшщыэюя')
    assert ob.plan_rows(False, True, platega=False) == [(ob.plan_rows(False, True, platega=False)[0][0], 'buy:premium_week')]


def test_showcase_window_and_captions():
    from services import first_offer_service as fos
    now = dt.datetime(2026, 11, 5, 12, 0)
    assert fos.is_showcase(now - dt.timedelta(minutes=20), now)
    assert not fos.is_showcase(now - dt.timedelta(hours=fos.SHOWCASE_HOURS + 1), now)
    assert not fos.is_showcase(None, now)
    cap = fos.showcase_caption('ru', '99 ₽', 3)
    assert '99 ₽' in cap and 'без автопродления' in cap
    assert 'no auto-renewal' in fos.showcase_caption('en', '75 Stars', 3)
    assert fos.FIRST_OFFER_MIN_MESSAGES == 2 and fos.FIRST_OFFER_PAUSE_MINUTES == 8


def test_showcase_voice_then_card_and_photo_after_payment():
    i = SCHED.index('async def _first_offer(bot):')
    body = SCHED[i:SCHED.index('async def _showcase_voice(', i)]
    assert body.index('fos.mark_offered(telegram_id)') < body.index('await _showcase_voice(')
    assert body.index('await _showcase_voice(') < body.index('await bot.send_photo(')
    assert 'fos.remember_photo(' in body and 'offer_buttons.plan_rows(trial,en)' in body
    assert 'await _deliver_showcase_photo(telegram_id, uid, lang)' in MAIN
    assert 'fos.take_pending_photo' in MAIN


def test_heavy_offer_text_is_honest_and_scheduled():
    from services import heavy_offer as ho
    assert ho.MIN_MESSAGES == 150
    assert ho.rounded(237) == 200 and ho.rounded(512) == 500 and ho.rounded(160) == 150
    ru, en = ho.text(237, 'ru'), ho.text(237, 'en')
    assert '200' in ru and 'один раз' in ru and 'ничего не поменяется' in ru
    assert 'nothing changes' in en
    for bad in ('осталось', 'только сегодня', 'обижусь', 'последний шанс'):
        assert bad not in ru
    assert "scheduler.add_job(_heavy_offer,'interval',minutes=30" in SCHED
    i = SCHED.index('async def _heavy_offer(bot):')
    body = SCHED[i:SCHED.index('async def _trial_followup(bot):', i)]
    assert body.index('ho.mark,') < body.index('await bot.send_message(')
    assert '_msk_daytime()' in body and 'is_premium(telegram_id)' in body


def test_en_pay_path_in_bot_chat():
    assert 'def _premium_keyboard_en(' in MAIN
    assert 'return _premium_keyboard_en(discount, telegram_id)' in MAIN
    assert "'premium_trial': lambda: ('Premium trial'" in MAIN
    assert 'title, description = _invoice_texts_en(chat_id, title, description, payload)' in MAIN
    assert "text='💎 Pay', url=link" in MAIN
    assert 'Free Premium demo for' in MAIN
