"""V3.168.0: shop screen, renewal trigger, morning callback, 90 s 18+ nudge."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _src(p):
    return (ROOT / p).read_text(encoding='utf-8')


def test_renewal_rails_are_on_by_default():
    import config
    for rail in ('renewal_care', 'paid_day1', 'trial_followup'):
        assert rail in config.PUSH_RAILS_DEFAULT.split(',')


def test_renewal_sees_expired_rows_and_waits_two_hours():
    s = _src('services/renewal_care.py')
    assert "Subscription.status.in_(('active', 'expired'))" in s
    assert 'ENDED_MIN_HOURS' in s and 'open_winback_bonus' in s
    import services.renewal_care as rc
    assert rc.SOON_HOURS >= 26 and rc.ENDED_MIN_HOURS == 2


def test_renewal_night_is_shifted_to_ten_not_cancelled():
    s = _src('services/scheduler_service.py')
    assert 'def _care_daytime' in s and '10 <= (now.hour + 3) % 24' in s
    assert 'rc.ENABLED and _care_daytime()' in s
    assert 'allow_push' not in s.split('async def _renewal_care')[1].split('async def _autopay_scan')[0]


def test_morning_callback_runs_on_the_live_ritual_path():
    s = _src('services/scheduler_service.py')
    body = s.split('async def _ritual_line_push')[1].split('async def _rituals')[0]
    assert 'morning_callback' in body and "return 'callback'" in body
    assert "len(mine) < 2" in _src('services/chat_service.py')


def test_adult_nudge_90_seconds_two_buttons_no_governor():
    import services.first_minutes as fm
    assert fm.ADULT_NUDGE_SECONDS == 90 and len(fm.ADULT_NUDGE_OPTIONS) == 2
    s = _src('services/scheduler_service.py')
    body = s.split('async def _adult_nudge')[1].split('async def _heavy_offer')[0]
    assert 'allow_push' not in body and 'actions=actions' in body
    assert "id='adult_nudge'" in s


def test_onboarding_funnel_events():
    m = _src('main.py')
    assert "'onboarding_catalog_opened'" in m and "'onboarding_character_selected'" in m


def test_shop_has_sticky_pay_and_method_switch_above_plans():
    h = _src('webapp/index.html')
    assert 'class="pc-sticky"' in h and 'position: sticky; bottom: calc(68px' in h
    assert h.index('${paySw}') < h.index("${plans.map(planRow).join('')}")
    assert "verb + ' ' + planPrice(x)" in h
    assert 'L.prem_list.slice(1, 4)' in h


def test_offer_autoshow_points():
    h = _src('webapp/index.html')
    assert "setTimeout(() => quickBuy('peaches'), 400)" in h
    assert "j.photo_block === 'free_used' && !(ME && ME.premium)" in h
    assert "if (err === 'limit') showTab('shop')" not in h
    assert "'speak_premium_wall'" in _src('main.py')
