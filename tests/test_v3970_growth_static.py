"""V3.97.0 — growth pack from the 1 Nov 2026 stats review.

- no more «хм… я зависла на секунду 🙈»: an empty dialogue answer retries
  MiniMax with more room, then she answers with a live «busy» line;
- 3 free message voice generations per account/day, then explicit paid consent;
- the 99 ₽ trial on the bot's «she fell asleep» wall and on the chat chips;
- a one-time −50% month for users who keep hitting the limit;
- she writes before and after the trial ends;
- the morning continues yesterday's talk;
- one nudge for people quiet in their first ten minutes;
- a weekly report to the owner (Monday + /week), «Девушка дня» tagged.
Offline regression checks, no network.
"""
import ast
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
LLM = (ROOT / 'services' / 'llm_provider_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
PAY = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')
WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')


def test_no_frozen_fallback_line():
    # V3.167.1 (владелец): живых фраз-оправошников больше нет — одна нейтральная
    # заглушка про связь, и она не пишется в диалог.
    assert 'def stall_line(' not in CHAT
    assert 'def stub_reply(' in CHAT
    assert 'answer, thought, draft = stub_reply(' in CHAT


def test_the_retired_stall_lines_stay_out_of_the_prompt():
    from services.chat_service import is_stall_line, _RETIRED_STALL_LINES
    for line in _RETIRED_STALL_LINES:
        assert is_stall_line(line), line
        assert is_stall_line(line[:16]), line
    assert not is_stall_line('ок')
    assert not is_stall_line('')


def test_empty_dialogue_retries_minimax_with_more_room():
    assert "RETRY_EMPTY_PURPOSES = frozenset({'dialogue'})" in LLM
    assert 'retry_headroom = MINIMAX_EMPTY_RETRY_HEADROOM' in LLM
    assert 'max_tokens=max_tokens + room' in LLM
    assert "_MINIMAX_HEADROOM_BY_PURPOSE['dialogue']" in LLM


def test_free_voice_listens(monkeypatch):
    import config
    from models.app_models import Message, ProductEvent, User
    from services import message_voice_service as voices
    from services.db import SessionLocal

    assert config.SPEAK_FREE_PER_DAY >= 0
    monkeypatch.setattr(voices, 'SPEAK_FREE_PER_DAY', 3)
    monkeypatch.setattr(voices, 'ADMIN_TELEGRAM_IDS', set())
    now = datetime(2026, 11, 18, 12)
    monkeypatch.setattr(voices, '_now', lambda: now)
    telegram_id = uuid4().int % 10 ** 12
    with SessionLocal.begin() as s:
        user = User(telegram_id=str(telegram_id), bonus_peaches=7, photo_credits=73)
        other = User(telegram_id=str(telegram_id + 10 ** 12))
        s.add_all([user, other])
        s.flush()
        uid = user.id
        # Neither another account's usage nor yesterday/tomorrow's usage may
        # consume today's taste. Switching characters must NOT reset it.
        s.add_all([ProductEvent(user_id=owner, event_name='speak_free', created_at=when)
                   for owner, when in ((uid, now - timedelta(days=1)),
                                       (uid, now + timedelta(days=1)), (other.id, now))])
        messages = [Message(user_id=uid, character_id=cid, role='assistant',
                            content='A visible stored reply.')
                    for cid in ('anna_01', 'eva_01', 'anna_01', 'eva_01')]
        s.add_all(messages)
        s.flush()
        sources = [(m.character_id, m.id) for m in messages]
    for left, (cid, mid) in zip((2, 1, 0), sources[:3]):
        result = voices.reserve(telegram_id, cid, mid)
        assert result['ok'] and result['status'] == 'pending'
        assert result['free_left'] == left and result['charged'] == 0
    cid, mid = sources[3]
    assert voices.reserve(telegram_id, cid, mid) == {
        'ok': False, 'error': 'payment_required', 'price': voices.SPEAK_PEACH_COST}
    with SessionLocal() as s:
        assert s.query(ProductEvent).filter(
            ProductEvent.user_id == uid, ProductEvent.event_name == 'speak_free',
            ProductEvent.created_at >= now.replace(hour=0),
            ProductEvent.created_at < now.replace(hour=0) + timedelta(days=1)).count() == 3
        user = s.get(User, uid)
        assert (user.bonus_peaches, user.photo_credits) == (7, 73)
    # The route forwards the reservation's remaining count; the UI still
    # displays it. These pins are scoped to the actual handling functions.
    handler = next(n for n in ast.parse(MAIN).body
                   if isinstance(n, ast.AsyncFunctionDef) and n.name == '_webapp_api_chat_speak')
    body = ast.get_source_segment(MAIN, handler)
    assert 'voices.reserve, telegram_id, character_id, message_id' in body
    assert "payload['free_left'] = reservation['free_left']" in body
    start = SPA.index('async function speakLazy(')
    assert 'L.speak_free_left(j.free_left)' in SPA[start:SPA.index('\n}', start) + 2]


def test_trial_on_sleep_wall_and_chips():
    # V3.166.2: the «she fell asleep» wall is gone — it is one button to the
    # payment sheet now, so the trial row lives on the ordinary Premium
    # keyboard (ru + en) instead of stacking offers on top of the wall.
    wall = MAIN[MAIN.index('def _limit_wall_markup('):MAIN.index('# V3.27.0: ruble-shop balances')]
    assert 'buy:premium_trial' not in wall
    assert MAIN.count("callback_data='buy:premium_trial'") >= 2
    assert 'function trialChip(' in SPA
    assert "quickBuy('spicy')\">${esc(trialChip(" in SPA


def test_vip_offer_wired_end_to_end():
    from services import vip_offer
    assert vip_offer.PRODUCT == 'premium_month_vip'
    assert vip_offer.VIP_STARS < 500
    assert '"premium_month_vip"' in PAY
    assert "payload=='premium_month_vip'" in MAIN          # pre-checkout check
    assert "if payload == 'premium_month_vip':" in MAIN     # grant
    assert "if product == 'premium_month_vip':" in MAIN     # platega amount + gate
    assert "'premium_vip': 'premium_month_vip'" in MAIN     # app SBP order key
    assert "@dp.callback_query(F.data == 'buy:premium_vip')" in MAIN
    assert "'id': 'premium_vip'" in WEB
    # V3.166.2 owner ruling («размывают фокус»): the wall stopped opening this
    # window, so the app sheet never receives the flag. The product itself
    # stays — an order placed before the release still has to resolve.
    assert 'vip: !!jl.vip' not in SPA
    assert 'opts.vip' not in SPA


def test_trial_followup_and_first_minutes_jobs():
    assert "id='trial_followup'" in SCHED
    assert "id='first_minutes'" in SCHED
    assert "id='weekly_report'" in SCHED
    from services import trial_followup, first_minutes
    assert trial_followup.text('soon', '', 'ru') and trial_followup.text('ended', '', 'en')
    # nothing adult before consent
    assert '18' in first_minutes.text('consent', 'ru')


def test_morning_callback():
    assert 'async def morning_callback(' in CHAT
    assert 'morning_callback_sent' in SCHED


def test_weekly_report_and_girlday_tag():
    assert "@dp.message(Command('week'))" in MAIN
    assert "'girlday': _gd" in MAIN
    from services.weekly_report import render
    d = {'days': 7, 'new': 1, 'new_wrote': 1, 'active': 2, 'messages': 3, 'd1': 10.0, 'rub': 99,
         'stars': 0, 'payers': 1, 'by_product': [('premium_trial', 1)], 'girlday_msgs': 0,
         'agata': (0, 0), 'top': [], 'sources': []}
    text = render(d)
    assert '99 ₽' in text and 'Девушка дня' in text
