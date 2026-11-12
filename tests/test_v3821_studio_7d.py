"""V3.82.1: /stats studio health counts the last 7 days, not all time."""


def test_recent_totals_and_snapshot_hide_day_rows():
    from services.db import init_db
    init_db()
    from services import provider_stats_service as P
    ok0, fail0 = P.recent_totals('photo/')
    P.record_provider('photo/test_engine', True)
    P.record_provider('photo/test_engine', False, 'boom')
    P.record_provider('video/test_engine', False, 'boom')
    ok, fail = P.recent_totals('photo/')
    assert (ok - ok0, fail - fail0) == (1, 1)
    names = [r['provider'] for r in P.provider_snapshot()]
    assert 'photo/test_engine' in names
    assert not any(n.startswith(P.DAY_PREFIX) for n in names)
