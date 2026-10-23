"""V3.80.0: a referral pays 1 000 🍑 to both sides only after the friend's
10th real message, exactly once."""
from datetime import datetime, timedelta, timezone


def _say(uid, texts, start):
    from services.db import SessionLocal
    from models.app_models import Message
    with SessionLocal() as s:
        for i, t in enumerate(texts):
            s.add(Message(user_id=uid, character_id='anna_01', role='user', content=t,
                          created_at=start + timedelta(seconds=30 * i)))
        s.commit()


def _credits(tid):
    from services.user_service import get_user
    return get_user(tid).photo_credits or 0


def test_referral_pays_after_ten_real_messages():
    from services.db import init_db
    init_db()
    from services import referral_service as R
    from services.user_service import ensure_user, get_user
    from config import REFERRAL_INVITEE_CREDITS, REFERRAL_REFERRER_CREDITS, REFERRAL_QUALIFY_MESSAGES
    assert REFERRAL_INVITEE_CREDITS == 1000 and REFERRAL_REFERRER_CREDITS == 1000
    assert REFERRAL_QUALIFY_MESSAGES == 10
    ref_tid, inv_tid = 980001, 980002
    ensure_user(ref_tid)
    ensure_user(inv_tid)
    r0, i0 = _credits(ref_tid), _credits(inv_tid)
    assert R.apply_referral(inv_tid, ref_tid)['status'] == 'pending'
    assert (_credits(ref_tid), _credits(inv_tid)) == (r0, i0)   # nothing at signup
    uid = get_user(inv_tid).id
    start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    # junk does not count: one-word, repeats
    _say(uid, ['ок', 'привет', 'как дела у тебя'] * 3, start)
    assert R.qualify_referral(inv_tid) is None
    _say(uid, [f'мне нравится вариант номер {w}' for w in
               ['один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь']],
         start + timedelta(minutes=10))
    assert R.qualify_referral(inv_tid) is None          # 9 real so far
    res = R.qualify_referral(inv_tid, extra_text='а расскажи что делала вечером')
    assert res and res['referrer_telegram_id'] == ref_tid
    assert _credits(ref_tid) == r0 + 1000 and _credits(inv_tid) == i0 + 1000
    R._settled.clear()
    assert R.qualify_referral(inv_tid, extra_text='ещё одно длинное сообщение') is None
    assert _credits(ref_tid) == r0 + 1000
    prog = R.invite_progress(ref_tid)
    assert prog['invited'] == 1 and prog['waiting'] == 0 and prog['peaches'] == 1000


def test_unreferred_user_is_settled_fast():
    from services.db import init_db
    init_db()
    from services import referral_service as R
    from services.user_service import ensure_user
    ensure_user(980010)
    assert R.qualify_referral(980010, extra_text='просто болтаю с ней') is None
    assert 980010 in R._settled
