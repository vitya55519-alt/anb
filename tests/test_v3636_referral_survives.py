"""V3.63.6: a friend's invite survives a redeploy and a slow 18+ tap."""
from datetime import timedelta


def test_pending_referral_survives_restart(monkeypatch):
    from services.db import init_db
    init_db()
    from services import referral_service as R
    monkeypatch.setattr('services.consent_service.has_accepted', lambda tid: False)
    R.remember_referral(900001, 900002)
    R._pending_referrals.clear()          # simulate a Railway redeploy
    assert R.pending_referral(900001) == 900002
    assert R.pending_referral(900001) is None   # consumed once


def test_existing_user_link_tap_is_ignored(monkeypatch):
    from services.db import init_db
    init_db()
    from services import referral_service as R
    monkeypatch.setattr('services.consent_service.has_accepted', lambda tid: True)
    R.remember_referral(900011, 900012)
    assert R.pending_referral(900011) is None


def test_new_user_window_is_a_day():
    from services import referral_service as R
    assert R._NEW_USER_WINDOW == timedelta(hours=24)
