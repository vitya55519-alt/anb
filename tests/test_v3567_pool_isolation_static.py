# -*- coding: utf-8 -*-
"""V3.56.7 static pins: the proactive media pool is per-character.

Owner's bug: Nadya (constructor persona) delivered a stranger's photo —
ProactivePhoto rows had no owner, and random_proactive_photo() picked from
the whole global pool for every girl's rituals/gifts/life-moments.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
RFS = (ROOT / 'services' / 'retention_features_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
PPS = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')
LIFE = (ROOT / 'services' / 'life_event_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


# ── schema: every shot belongs to one character ─────────────────────────────
def test_pool_row_has_character():
    pool = MODELS[MODELS.index('class ProactivePhoto(Base):'):MODELS.index('class ', MODELS.index('class ProactivePhoto(Base):') + 10)]
    assert 'character_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)' in pool


# ── service: strict per-character pick + re-tag CRUD ────────────────────────
def test_random_pick_is_character_strict():
    pick = RFS[RFS.index('def random_proactive_photo('):RFS.index('def get_character_miss(')]
    assert 'def random_proactive_photo(character_id: str | None = None)' in pick
    assert 'ProactivePhoto.character_id == character_id' in pick
    # no-argument legacy call must not silently return everyone's media
    assert 'if character_id:' in pick


def test_retag_and_add_carry_character():
    assert 'def set_proactive_photo_character(photo_id: int, character_id: str) -> bool:' in RFS
    assert 'kind=kind, character_id=character_id or None))' in RFS
    assert "'character_id': getattr(r, 'character_id', None) or ''," in RFS


# ── senders: all three proactive rails pass the real character ──────────────
def test_ritual_uses_user_selected_character():
    ritual = SCHED[SCHED.index('async def _rituals(bot):'):SCHED.index('async def _donation_reminder(bot):')]
    assert 'u.selected_character or ' in ritual          # snapshot carries it
    assert "char_id = sel_char or CHARACTER_ID or 'anna_01'" in ritual
    assert 'random_proactive_photo(char_id)' in ritual


def test_gift_and_life_event_are_per_character():
    gift = PPS[PPS.index('async def send_daily_gift('):]
    assert 'gift_char = user.selected_character or CHARACTER_ID' in gift
    assert 'random_proactive_photo(gift_char)' in gift
    assert "'gift', gift_char, 'daily_gift'" in gift
    assert 'photo = random_proactive_photo(character_id)' in LIFE


# ── admin UX: upload asks whose face it is; shots can be re-tagged ──────────
def test_admin_flow_binds_character():
    assert 'PROPHOTO_WAIT: dict[int, str] = {}' in MAIN
    assert 'PROPHOTO_TAG_WAIT: dict[int, int] = {}' in MAIN
    assert "callback_data=f'admin:prophoto:pick:{c.character_id}'" in MAIN
    assert "F.data.startswith('admin:prophoto:tag:')" in MAIN
    assert 'rfs.set_proactive_photo_character(tag_id, char_id)' in MAIN
    # the pool screen labels each shot with its girl
    assert "tag = names.get(_cid, _cid)[:10] if _cid else '❓'" in MAIN
