"""V3.84.0: 5 friends who each wrote 5 real messages → 1 day Premium."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ladder_has_five_friend_premium_day():
    import config
    assert config.REFERRAL_QUALIFY_MESSAGES == 5
    assert (5, 0, 1) in config.REFERRAL_BONUS_TIERS
    assert [t[0] for t in config.REFERRAL_BONUS_TIERS] == [3, 5, 10, 25]


def test_tier_granted_matched_by_invite_count_not_index():
    from services.db import init_db, SessionLocal
    init_db()
    from services import referral_service as R
    from services.user_service import ensure_user
    from models.app_models import ProductEvent
    uid = ensure_user(984001)
    # an old marker for the 10-friend tier written when it was index 1
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=uid, event_name='referral_tier_1', value=0.0,
                           metadata_json=json.dumps({'invites': 10, 'credits': 3000, 'premium_days': 7})))
        s.commit()
    assert R._tier_already_granted(uid, 2, 10) is True    # old 10-tier, now index 2
    assert R._tier_already_granted(uid, 1, 5) is False    # the new 5-tier is still open


def test_zero_peach_tier_is_not_shown_as_plus_zero():
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert "[f'+{t[\"credits\"]} 🍑'] if t['credits'] else []" in main
    index = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    assert "(p && p !== '0') ? '+' + p + ' 🍑' : ''" in index
