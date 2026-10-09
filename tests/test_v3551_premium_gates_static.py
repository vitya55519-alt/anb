"""V3.55.1: free tier 30 messages/day + voice replies become a Premium perk.

Owner decisions pinned here:
1. FREE_MESSAGES_PER_DAY default dropped 50 → 30 (Premium «безлимит» bites).
2. The bot's voice-reply path (send_answer) only synthesizes for premium or
   admin; a non-premium voice user gets text plus a once-a-day paywall nudge
   stamped in DialogStore('voice_premium_hint') — no schema change.
3. The Mini App chat-media endpoint gates kind='voice' behind premium_required
   exactly like circles; the SPA already maps that error to the paywall toast.
4. Paid experiences keep their voice: the Stars gift/date _send_voice_note and
   the 3🍑 voice+photo combo are NOT gated (a paid product stays paid-full).
5. The premium pitch (RU+EN) advertises the new perk.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_free_message_limit_is_thirty():
    # V3.57.6: the owner lifted the chat brake 30 → 3000/day (fair-use ceiling).
    # The test name keeps the old number as history; the pin tracks the default.
    assert 'FREE_MESSAGES_PER_DAY = int(os.getenv("FREE_MESSAGES_PER_DAY", "3000"))' in CONFIG


def test_send_answer_voice_requires_premium():
    fn = MAIN[MAIN.index('async def send_answer('):MAIN.index('@dp.message(F.text.in_(kb_pair(\'chat\')))')]
    assert 'user.voice_enabled and (is_premium(message.from_user.id) or message.from_user.id in ADMIN_TELEGRAM_IDS)' in fn
    # the once-a-day nudge rides DialogStore and can never break the reply
    assert "_voice_premium_hint = dialog_store.DialogStore('voice_premium_hint')" in MAIN
    assert 'if _voice_premium_hint.get(message.from_user.id) != today:' in fn
    assert 'привилегия Premium' in fn
    assert 'except Exception:' in fn


def test_app_chat_voice_premium_gate():
    start = MAIN.index("async def _webapp_api_chat_media(")
    gate = MAIN[start:MAIN.index('async def _webapp_media(request', start)]
    assert "if kind == 'voice' and telegram_id not in ADMIN_TELEGRAM_IDS and not is_premium(telegram_id):" in gate
    assert gate.count("'error': 'premium_required'}, status=403") >= 3  # card, circle, video, voice


def test_paid_voice_experiences_stay_ungated():
    # gifts/dates voice note: only the user's own toggle gates it, not premium
    note = MAIN[MAIN.index('async def _send_voice_note('):]
    note = note[:note.index('async def ', 10)] if 'async def ' in note[10:] else note
    assert "getattr(user, 'voice_enabled', False)" in note
    assert 'is_premium' not in note
    # the 3🍑 voice+photo combo keeps its peach price
    assert 'VOICE_PHOTO_PEACH_COST' in MAIN


def test_voice_toggle_and_pitch_advertise_the_perk():
    assert 'голос — привилегия Premium' in MAIN
    assert "'• 🎙 голосовые ответы — только для Premium'," in MAIN
    assert "'• 🎙 voice replies — Premium only'," in MAIN
