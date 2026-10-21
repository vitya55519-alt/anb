"""V3.64.8: from Витя's screenshots: the daily gift and the morning ritual
sent the same pool photo every time, life moments arrived cut off
(«Надела сегодня тот», «perspective,»), the morning caption doubled the
greeting with a double space and had the gift promo glued in."""
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from models.waifu_models import Base  # noqa: E402
from services.db import engine  # noqa: E402
from services import retention_features_service as rfs  # noqa: E402
from services.dialogue_guard_service import finish_or_drop  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def setup_module(_m):
    import models.app_models  # noqa: F401  registers the tables
    Base.metadata.create_all(engine)


def test_pool_photo_rotates_per_user_without_repeats():
    for i in range(3):
        assert rfs.add_proactive_photo(b'img%d' % i + b'x' * 50, 'image/jpeg', 'photo', character_id='rot_girl')
    seen = [rfs.random_proactive_photo('rot_girl', user_id=4242)[0] for _ in range(3)]
    assert len(set(seen)) == 3                      # every shot once before a repeat
    fourth = rfs.random_proactive_photo('rot_girl', user_id=4242)[0]
    assert fourth == seen[0]                         # then the one seen longest ago
    other = {rfs.random_proactive_photo('rot_girl', user_id=777)[0] for _ in range(3)}
    assert len(other) == 3                          # another user has his own rotation


def test_cut_off_or_foreign_text_is_dropped():
    assert finish_or_drop('Надела сегодня тот', complete=False) == ''
    assert finish_or_drop('perspective,') == ''
    assert finish_or_drop('сегодня была на йоге 😌 а потом пошла в тот', complete=False) == 'сегодня была на йоге 😌'
    assert finish_or_drop('сижу в кафе, угадай с кем?') == 'сижу в кафе, угадай с кем?'
    assert finish_or_drop('hey, guess where I am', lang='en') == 'hey, guess where I am'


def _resp(text, finish='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)], usage=None)


def test_gemini_gets_thinking_room_and_reports_cut(monkeypatch):
    from services import llm_provider_service as L
    seen = {}

    async def gem_create(**k):
        seen['max'] = k['max_tokens']
        return _resp('Надела сегодня тот', 'length')
    monkeypatch.setattr(L, '_minimax', None)
    monkeypatch.setattr(L, '_gemini', SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=gem_create))))
    r = asyncio.run(L.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=90, purpose='life_event'))
    assert seen['max'] == 90 + L.GEMINI_REASONING_HEADROOM
    assert r.complete is False


def test_minimax_gets_more_room_for_first_messages(monkeypatch):
    from services import llm_provider_service as L
    seen = {}

    async def mm_create(**k):
        seen['max'] = k['max_tokens']
        return _resp('угадай, где я сейчас 😏')
    monkeypatch.setattr(L, '_minimax', SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=mm_create))))
    r = asyncio.run(L.generate_text([{'role': 'user', 'content': 'x'}], max_tokens=90, purpose='life_event'))
    assert seen['max'] == 90 + 1200 and r.complete is True


def test_fixed_texts_have_no_double_spaces_or_dashes():
    for kind in ('morning', 'evening', 'miss', 'jealousy', 'cliffhanger'):
        for _ in range(30):
            t = rfs.get_retention_text(kind, 'vika_01')
            assert '  ' not in t and ' — ' not in t and t == t.strip()
    assert rfs.tidy_fixed_text('утро  у меня перерыв через час.') == 'утро у меня перерыв через час'


def test_morning_caption_is_her_words_and_gift_is_a_button():
    sched = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
    ritual = sched[sched.index('async def _rituals(bot):'):sched.index('async def _donation_reminder(bot):')]
    assert 'text+=f"\\n🎁 забирай' not in ritual
    assert "gift_label=f\"🎁 Забрать подарок +{gs.get('amount',1)} 🍑\"" in ritual
    assert 'text=random.choice(_PROMISE_KEPT)' in ritual   # one greeting, not two
    assert "'как обещала 🙈 доброе утро\\n\\n'+text" not in ritual


def test_proactive_never_sends_half_a_sentence():
    src = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
    pro = src[src.index('async def proactive_reply('):src.index('async def story_reaction(')]
    assert 'finish_or_drop(raw' in pro and "get_retention_text('miss', character_id)" in pro
    life = (ROOT / 'services' / 'life_event_service.py').read_text(encoding='utf-8')
    assert "finish_or_drop(text, getattr(r, 'complete', True))" in life
