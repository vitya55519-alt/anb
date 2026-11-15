"""V3.62.9 pinned the level-up message that opened the one-time −30% Premium
window. V3.166.2 (owner — «разовая скидка -30% размывает фокус») took the offer
out, so those two tests went with it; the pay-funnel snapshot stays here."""


def test_pay_funnel_in_snapshot():
    from services.analytics_service import admin_snapshot
    pf = admin_snapshot()['pay_funnel']
    assert set(pf) == {'offer', 'invoice', 'paid'}
