"""V3.59.0: engagement basics — honest D1, a day-0 funnel, she writes first,
and pushes come from the user's own girl."""
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-for-static-tests-only")

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
ANALYTICS = (ROOT / 'services' / 'analytics_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')


def test_retention_counts_mini_app_activity():
    rr = ANALYTICS[ANALYTICS.index('def _retention_rate('):ANALYTICS.index('def onboarding_funnel(')]
    assert 'ProductEvent.event_name.in_(ACTIVE_EVENTS)' in rr
    for ev in ('chat_user_message', 'webapp_opened', 'webapp_chat_message', 'quest_route_completed'):
        assert f"'{ev}'" in ANALYTICS[ANALYTICS.index('ACTIVE_EVENTS = ('):ANALYTICS.index('def _retention_rate(')]
    for pushed in ('proactive_sent', 'retention_push_sent', 'day1_hook_sent'):
        assert f"'{pushed}'" not in ANALYTICS[ANALYTICS.index('ACTIVE_EVENTS = ('):ANALYTICS.index('def _retention_rate(')]


def test_funnel_reaches_both_stats_screens():
    assert "'funnel': onboarding_funnel()," in ANALYTICS
    assert 'воронка 30д' in MAIN and 'Funnel 30d' in MAIN


def test_the_bot_stays_silent_after_consent():
    h = MAIN[MAIN.index('async def consent_accept('):MAIN.index("@dp.callback_query(F.data == 'consent:terms')")]
    # V3.148.0: «she writes first» is off — the 18+ tap only rewrites the start
    # bubble, and the LLM speaks after he opens her chat and writes to her.
    assert '_first_hello' not in h
    assert 'donation_appeal' not in h and 'ref_link' not in h
    assert "save_message, uid, character_id, 'assistant', greeting" not in h


def test_the_first_hello_machinery_is_gone():
    import main
    for name in ('_first_hello', '_FIRST_HELLO', '_GENERIC_FIRST_HELLO', 'FIRST_REPLIES',
                 '_first_hello_keyboard', 'first_reply_cb', '_deliver_first_hello',
                 '_first_hello_fallback', '_send_welcome_selfie', '_ensure_webapp_first_hello'):
        assert not hasattr(main, name), name


def test_pushes_use_the_selected_character():
    pro = SCHED[SCHED.index('async def _proactive('):SCHED.index('async def _day1_hook(')]
    assert "char_id=(getattr(u,'selected_character','') or '').strip() or CHARACTER_ID" in pro
    assert 'proactive_reply(telegram_id,name,hours,character_id=char_id' in pro  # V3.101.0 adds topic=True
    assert 'CharacterState.character_id==char_id' in pro
