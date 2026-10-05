"""V3.52.0 — «Жизнь без тебя» (proactive life moments) + Mini App unread badges.

Two coupled features that both fight the D1 4% / D7 1% retention hole:

1. A character occasionally writes first about something from HER own day,
   grounded in her own personality (pace / tastes) plus a shared memory, and
   ends on an open loop with one-tap reply buttons. Photos come from the
   existing media pool only, never a fresh provider render.

2. Whatever she sends proactively surfaces as an UNREAD pill in the Mini App
   «Чаты» tab. Read-state lives in dialog_sessions (a DialogStore), NOT an
   in-memory dict, because Railway redeploys were wiping guards and letting the
   same push double-fire — the exact complaint behind the retention drop.

Static pins only (no imports -> the suite runs without a DB or an LLM key)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
LIFE = (ROOT / 'services' / 'life_event_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
CHAT_SVC = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_life_event_config_knobs():
    for knob in ('LIFE_EVENTS_ENABLED', 'LIFE_EVENTS_MAX_PER_DAY',
                 'LIFE_EVENTS_SCAN_MINUTES', 'LIFE_EVENTS_ACTIVE_WINDOW_DAYS',
                 'LIFE_EVENTS_QUIET_START_HOUR', 'LIFE_EVENTS_QUIET_END_HOUR',
                 'LIFE_EVENTS_PHOTO_CHANCE'):
        assert knob in CONFIG


def test_life_service_grounds_personality_and_fails_silent():
    # grounded in the SELECTED character's own temperament, not a generic Anna
    assert 'PACE_HINTS.get(' in LIFE
    # pulls shared history + the user's own unfinished topic
    assert 'get_memories' in LIFE
    assert 'get_state' in LIFE and 'pending_hook' in LIFE
    # photo only from the free pool, never a paid render
    assert 'random_proactive_photo' in LIFE
    assert 'purpose=' in LIFE and "'life_event'" in LIFE
    # one-tap buttons carry the character so the callback continues HER story
    assert 'life_reply:' in LIFE
    assert 'def tap_reply_text' in LIFE
    # fail-silent: empty / error path returns {} so a scan can never blank a chat
    assert 'return {}' in LIFE
    assert 'if len(text) < 8' in LIFE


def test_scheduler_persists_dedup_and_registers_job():
    # redeploy-safe dedup (dialog_sessions), not the in-memory _ritual_sent set
    assert "DialogStore('life_events')" in SCHED
    assert 'async def _life_events(bot)' in SCHED
    assert 'from services.life_event_service import build_life_moment' in SCHED
    # persisted into the shared dialog so the Mini App badge lights up
    assert 'save_message(uid, char_id, ' in SCHED
    assert "webapp_service.save_chat_media" in SCHED
    # analytics + quiet-hours + active-window gating
    assert "'life_event_sent'" in SCHED
    assert '_in_quiet_hours' in SCHED and 'LIFE_EVENTS_ACTIVE_WINDOW_DAYS' in SCHED
    # registered only when enabled, scanning on the configured cadence
    assert "id='life_events'" in SCHED
    assert 'LIFE_EVENTS_SCAN_MINUTES' in SCHED


def test_unread_is_computed_and_returned():
    # read-state persists across redeploys (DialogStore), not an in-memory dict
    assert "DialogStore('chat_reads')" in WEBAPP_SVC
    assert 'def mark_chat_read' in WEBAPP_SVC
    # unread = assistant messages newer than max(last user turn, last open)
    assert "'unread':" in WEBAPP_SVC
    # a conversational reply the user already saw is marked read immediately,
    # so only a LATER proactive message can light the badge again
    assert 'webapp_service.mark_chat_read(user_id, character_id)' in CHAT_SVC
    assert 'webapp_service.mark_chat_read(telegram_id, character_id)' in MAIN


def test_tap_back_continues_the_shared_reply_pipeline():
    # callback handler feeds the natural user line into anna_reply (bot + app
    # share the pipeline: memory, persona, relationship)
    assert "F.data.startswith('life_reply:')" in MAIN
    assert 'from services.life_event_service import tap_reply_text' in MAIN
    assert 'anna_reply' in MAIN[MAIN.index("def on_life_reply_tap"):]


def test_spa_badge_and_read_on_open():
    # renderChats draws the unread pill from the server's unread count
    assert 'c.unread' in SPA
    assert 'badge' in SPA[SPA.index('function renderChats'):]
    # opening a chat marks it read server-side and drops the cached list so the
    # pill clears on the next «Чаты» visit
    assert '_chatsLoaded = false' in SPA[SPA.index('function openChat'):]
