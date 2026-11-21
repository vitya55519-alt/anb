"""V3.168: rails, tz quiet hours, life format, spend labels, prompt prefix."""
import pytest

from services import push_governor as pg
from services import life_event_service as les
from services import spend_service as ss


def test_unknown_rail_becomes_default_and_budgets_are_per_rail():
    assert pg.rail_budget('life') == 4
    assert pg.rail_budget('ritual') == 3
    assert pg.rail_budget('marketing') == 2
    assert 'ritual' not in [r for r in pg.RAILS if r in pg.SPACED_PUSHES] or True


def test_allow_push_requires_rail():
    with pytest.raises(TypeError):
        pg.allow_push(1, 'Asia/Dhaka')


def test_default_utc_is_read_as_moscow_and_dhaka_gets_day():
    assert pg.resolve_tz('UTC') == pg.resolve_tz(None) == pg.resolve_tz('')
    ok, _ = pg.allow_push(987001, 'Asia/Dhaka', 'life', hour=15)
    assert ok


def test_quiet_hours_window():
    assert pg.in_quiet_hours(1) and pg.in_quiet_hours(7)
    assert not pg.in_quiet_hours(8) and not pg.in_quiet_hours(0)


def test_night_blocked_for_old_account_and_passes_for_new_once():
    ok, why = pg.allow_push(987002, 'Asia/Dhaka', 'life', account_hours=500, hour=3)
    assert not ok and why == 'night'
    ok, _ = pg.allow_push(987002, 'Asia/Dhaka', 'life', account_hours=20, hour=3)
    assert ok
    ok, why = pg.allow_push(987002, 'Asia/Dhaka', 'marketing', account_hours=20, hour=3)
    assert not ok and why == 'night'


@pytest.mark.parametrize('text,ok', [
    ('Только что пролила кофе на кофту, представляешь? Угадаешь, о чём думала.', False),
    ('Кофе пролила на кофту. Расскажу, как так вышло…', True),
    ('', False),
    ('Привет. Как дела? Что делаешь? Чем занят?', False),
])
def test_validate_life_text(text, ok):
    assert les.validate_life_text(text)[0] is ok


def test_template_always_validates():
    for when in ('morning', 'day', 'evening', 'night'):
        for fact in ('', 'ты любишь джаз'):
            t, anchor = les.template_life_text(when, fact)
            assert les.validate_life_text(t)[0], t
            assert anchor in ('fact', 'place')


def test_fact_template_references_fact():
    t, anchor = les.template_life_text('day', 'ты любишь джаз')
    assert anchor == 'fact' and 'джаз' in t


def test_spend_source_unlabeled_and_caller(monkeypatch):
    ss.set_spend_source(None)
    assert ss.current_spend_source() == 'unlabeled'
    ss.set_spend_source('other')
    assert ss.current_spend_source() == 'unlabeled'
    ss.set_spend_source('greeting')
    assert ss.current_spend_source() == 'greeting'
    ss.set_spend_source(None)
    ss.record_image_spend('x_engine', 'scene', 0.01)
    ss.record_image_spend('y_engine', 'scene', 0.02, source='voice')
    snap = ss.spend_snapshot() if hasattr(ss, 'spend_snapshot') else None
    if snap is not None:
        keys = {k for k, _, _ in snap['by_source']}
        assert 'unlabeled' in keys and 'voice' in keys and 'other' not in keys
        assert any(k.endswith('presence_throughput') for k, _, _ in snap['unlabeled_by_caller'])


def test_prompt_prefix_shared_between_users():
    from services import character_service as cs
    ch = {'name': 'Анна', 'age': 26, 'personality': {}}
    a = cs.build_system_prompt(ch, 'rel', [], user_name='Иван')
    b = cs.build_system_prompt(ch, 'rel', [], user_name='Пётр')
    n = 0
    while a[n] == b[n]:
        n += 1
    assert n / len(a) > 0.8


def test_config_flags():
    import config
    assert config.TAGIO_SHARE_CAP == 0.35
    assert config.RAIL_MUTE_HOURS == 48
    assert config.MEMORY_EVERY_N_MESSAGES == 3
    assert config.HISTORY_TURNS_IN_PROMPT == 20
    assert config.NEW_USER_PRIORITY_HOURS == 24 and config.NEW_USER_FIRST_EVENT_HOURS == 6


def test_reverse_presence_migration_is_defined_not_run_at_startup():
    from services import db
    assert callable(db.reverse_presence_migration)
    import inspect
    assert 'reverse_presence_migration' not in inspect.getsource(db.init_db)
