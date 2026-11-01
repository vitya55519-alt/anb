"""V3.97.0 — growth pack from the 1 Nov 2026 stats review.

- no more «хм… я зависла на секунду 🙈»: an empty dialogue answer retries
  MiniMax with more room, then she answers with a live «busy» line;
- 3 free «🔊» listens a day before the Premium wall;
- the 99 ₽ trial on the bot's «she fell asleep» wall and on the chat chips;
- a one-time −50% month for users who keep hitting the limit;
- she writes before and after the trial ends;
- the morning continues yesterday's talk;
- one nudge for people quiet in their first ten minutes;
- a weekly report to the owner (Monday + /week), «Девушка дня» tagged.
Static pins only, no network.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
LLM = (ROOT / 'services' / 'llm_provider_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
PAY = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')
WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')


def test_no_frozen_fallback_line():
    assert '"хм… я зависла на секунду 🙈"' not in CHAT
    assert 'def stall_line(' in CHAT
    assert 'answer = stall_line(_lang' in CHAT


def test_stall_line_avoids_recent_repeats():
    from services.chat_service import stall_line, STALL_LINES_RU, STALL_LINES_EN
    for line in STALL_LINES_RU:
        recent = [x for x in STALL_LINES_RU if x != line]
        assert stall_line('ru', recent) == line
    assert stall_line('en') in STALL_LINES_EN


def test_empty_dialogue_retries_minimax_with_more_room():
    assert "RETRY_EMPTY_PURPOSES = frozenset({'dialogue'})" in LLM
    assert 'max_tokens=max_tokens + MINIMAX_EMPTY_RETRY_HEADROOM' in LLM
    assert "_MINIMAX_HEADROOM_BY_PURPOSE['dialogue']" in LLM


def test_free_voice_listens():
    assert 'SPEAK_FREE_PER_DAY' in MAIN
    assert "chat_photo_allowance.count_today(uid, 'speak_free')" in MAIN
    assert "payload['free_left'] = free_left" in MAIN
    assert 'L.speak_free_left(j.free_left)' in SPA
    import config
    assert config.SPEAK_FREE_PER_DAY >= 0


def test_trial_on_sleep_wall_and_chips():
    assert "callback_data='buy:premium_trial')])\n            if PLATEGA_ENABLED and is_button_enabled('platega_rub'):" in MAIN
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
    assert "vip: !!jl.vip" in SPA


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
