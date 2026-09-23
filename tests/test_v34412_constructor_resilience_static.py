"""V3.44.12 static checks: constructor resilience + avatar figure lock.

1. The persona is saved even when avatar generation fails — «создал, а её нет
   нигде» must never happen again. The avatar is retried (3 attempts, then a
   delayed task at +5/+15 min) and healed lazily on the first photo request.
2. The constructor avatar prompt ends with a FINAL BODY LOCK so edit engines
   take the face from the reference but the figure from the constructor
   params (owner: «лицо передаёт отлично, а фигуру теряет»).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CCS = (ROOT / 'services' / 'custom_character_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def _finish_body() -> str:
    return MAIN[MAIN.index('async def _finish_constructor('):MAIN.index("@dp.callback_query(F.data == 'constructor:start')")]


def test_persona_saved_even_when_avatar_fails():
    body = _finish_body()
    assert 'for attempt in (1, 2)' in body
    assert 'asyncio.wait_for(' in body
    assert 'avatar_failed = avatar_bytes is None' in body
    # the DB save comes AFTER the avatar attempts — she exists no matter what
    assert body.index('save_custom_character(') > body.index('avatar_failed = avatar_bytes is None')
    # disk upload is guarded so a missing avatar cannot crash the save
    assert 'if avatar_bytes:' in body


def test_refund_still_fires_for_paid_runs():
    body = _finish_body()
    assert "elif source == 'peaches':" in body
    assert 'grant_photo_credits(' in body
    assert 'constructor_refund:' in body
    assert 'asyncio.create_task(_retry_constructor_avatar(telegram_id, row.character_id))' in body


def test_delayed_avatar_retry_task():
    assert 'async def _retry_constructor_avatar(telegram_id: int, character_id: str) -> None:' in MAIN
    assert 'for delay in (300, 900):' in MAIN
    assert 'set_custom_avatar_file_id(character_id, sent.photo[-1].file_id)' in MAIN


def test_set_avatar_file_id_helper():
    assert 'def set_custom_avatar_file_id(character_id: str, avatar_file_id: str) -> bool:' in CCS
    assert 'row.avatar_file_id = avatar_file_id' in CCS


def test_lazy_avatar_recovery_in_ensure():
    body = PHOTO[PHOTO.index('async def ensure_custom_avatar_cached('):]
    body = body[:body.index('\nasync def ')]
    assert 'if row.avatar_file_id:' in body
    assert 'generated-on-demand' in body
    assert 'lazy custom avatar generation failed' in body
    assert 'build_avatar_prompt(params)' in body


def test_avatar_prompt_final_body_lock():
    assert 'FINAL BODY LOCK (overrides the reference photo)' in CCS
    assert 'body_spec = custom_body_spec(params)' in CCS
    assert 'Take from the reference ONLY the face and identity' in CCS
