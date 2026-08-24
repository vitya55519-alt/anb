"""Static + runtime tests for v3.18.0: relationship system upgrade.

- Level-up ceremony via the stage-change notifier (fires from chat, gifts,
  dates, apartment) with unlock list and a celebration photo set.
- Profile card shows the bond character and per-axis progress to next stage.
- Instant feedback reaction on signal messages.
- LLM relationship pulse scores conversation quality every N messages.
- Reconnect moments for users returning after 3+ days.
- Gifts now also grow trust (attention buys warmth, not just affection).
"""
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
ENGINE = (ROOT / 'services' / 'relationship_engine.py').read_text(encoding='utf-8')
SERVICE = (ROOT / 'services' / 'relationship_service.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
PULSE = (ROOT / 'services' / 'relationship_pulse.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')


# ---------- static wiring ----------

def test_ceremony_notifier_registered():
    assert 'set_stage_change_notifier(_on_relationship_stage_up)' in MAIN
    assert 'def set_stage_change_notifier(' in SERVICE
    assert 'async def _on_relationship_stage_up(' in MAIN
    ceremony = MAIN[MAIN.index('async def _on_relationship_stage_up('):MAIN.index('set_stage_change_notifier(')]
    assert 'Новый этап:' in ceremony
    assert 'Теперь доступно:' in ceremony
    assert "'relationship_ceremony_sent'" in ceremony
    assert "_start_photo_background(telegram_id, telegram_id, PhotoRequest(scene='selfie', mood='romantic'), 'story')" in ceremony
    # Fires from record_user_message regardless of the caller.
    assert '_stage_change_notifier' in SERVICE


def test_profile_progress_and_bond():
    assert "'💞 Характер связи: {bond_title}\\n'" in MAIN
    assert "📈 До следующего этапа:" in MAIN
    assert 'def bond_character(' in ENGINE
    assert 'def next_stage_progress(' in ENGINE
    assert 'def progress_bar(' in ENGINE
    # Bond flavor also steers her chat tone.
    assert 'Характер вашей связи сейчас:' in ENGINE


def test_instant_feedback_reaction():
    assert "infer_delta" in MAIN
    assert "message.react([types.ReactionTypeEmoji(emoji='❤️')])" in MAIN


def test_relationship_pulse_service():
    assert 'RELATIONSHIP_PULSE_ENABLED' in CONFIG
    assert 'PULSE_EVERY = 8' in PULSE
    assert "purpose='relationship_pulse'" in PULSE
    assert "'inside_joke'" in PULSE and "'meaningful_share'" in PULSE
    assert "reason='llm_pulse'" in PULSE
    # Wired into the chat flow as a background task.
    assert 'maybe_pulse(user_id, user_name, character_id)' in CHAT


def test_reconnect_moment():
    assert 'reconnect_bonus = 1.5' in ENGINE
    assert 'if gap >= 3:' in ENGINE
    assert 'Пользователь вернулся после' in SERVICE


def test_gifts_grow_trust():
    assert MAIN.count("trust=max(0.5, round(gift.affection * 0.25, 2))") == 2


# ---------- runtime ----------

def _row(**kw):
    base = dict(stage='close', relationship_score=50.0, trust_score=40.0,
                intimacy_score=30.0, familiarity_score=0.0,
                continuity_score=0.0, connection_score=0.0)
    base.update(kw)
    return SimpleNamespace(**base)


def test_bond_character_flavors():
    from services.relationship_engine import bond_character
    assert bond_character(None)[0] == 'зарождающаяся симпатия'
    assert bond_character(_row(relationship_score=10, trust_score=10, intimacy_score=10))[0] == 'зарождающаяся симпатия'
    assert bond_character(_row(relationship_score=40, trust_score=40, intimacy_score=65))[0] == 'страстный роман'
    assert bond_character(_row(relationship_score=40, trust_score=65, intimacy_score=40))[0] == 'глубокое доверие'
    assert bond_character(_row(relationship_score=65, trust_score=40, intimacy_score=40))[0] == 'лёгкий флирт'
    assert bond_character(_row(relationship_score=45, trust_score=42, intimacy_score=40))[0] == 'гармоничная близость'


def test_next_stage_progress_targets():
    from services.relationship_engine import next_stage_progress
    prog = next_stage_progress(_row(stage='stranger', relationship_score=0, trust_score=0, intimacy_score=0))
    labels = [p[0] for p in prog]
    assert labels == ['❤️ отношения', '🤝 доверие', '🔥 страсть']
    # Next stage after stranger is acquaintance: 15/10/0.
    assert [p[2] for p in prog] == [15, 10, 0]
    # Final stage has nothing to chase.
    assert next_stage_progress(_row(stage='committed')) == []


def test_progress_bar_rendering():
    from services.relationship_engine import progress_bar
    assert progress_bar(5, 10) == '▓▓▓▓▓░░░░░'
    assert progress_bar(0, 10) == '░' * 10
    assert progress_bar(12, 10) == '▓' * 10


def test_pulse_parser():
    from services.relationship_pulse import _parse_pulse
    ok = _parse_pulse('ответ: {"warmth": 2, "trust": 3, "intimacy": 1, "events": ["callback", "hack"]}')
    assert ok == {'warmth': 2.0, 'trust': 3.0, 'intimacy': 1.0, 'events': ['callback']}
    assert _parse_pulse('no json here') is None
    clamped = _parse_pulse('{"warmth": 9, "trust": -2, "intimacy": "x", "events": []}')
    assert clamped == {'warmth': 3.0, 'trust': 0.0, 'intimacy': 0.0, 'events': []}
