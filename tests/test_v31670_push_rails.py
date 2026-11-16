# V3.167.0 — рельсы пушей и окна жизни (ТЗ Фогеля, владелец 16.11:
# «разрешаю по пушам», «2 возвращаем»).
#
# Механики не писали новых — их включили. С 13.11 всё, кроме её двух строк,
# было темно одним MARKETING_PUSH_ENABLED=false, и включить его одним тумблером
# значило затащить обратно и то, что дампом осудили (прогноз совместимости «это
# бред», «что нового», случайные подарки, «останешься?»). Поэтому PUSH_RAILS —
# список по именам, MARKETING_PUSH_ENABLED остаётся аварийным рубильником, а
# окно молчания её строк из него не ест.
#
# Второе, что умертвило вовлечение: окна «кого ещё трогать». При PROACTIVE_-
# MAX_INACTIVE_DAYS=10 человек, вернувшись на 11–20 день, не получал ничего.

import inspect

import config
from config import (
    INTERRUPT_MAX_PER_DAY,
    INTERRUPT_MIN_LEVEL,
    LIFE_EVENTS_ACTIVE_WINDOW_DAYS,
    LIFE_EVENTS_MAX_PER_DAY,
    LIFE_EVENTS_SILENCE_HOURS,
    LIFE_EVENTS_YOUNG_ACCOUNT_HOURS,
    LIFE_EVENTS_YOUNG_MAX_PER_DAY,
    LIFE_EVENTS_YOUNG_SILENCE_HOURS,
    MARKETING_PUSH_ENABLED,
    PROACTIVE_MAX_INACTIVE_DAYS,
    PUSH_RAILS,
    PUSH_RAILS_DEFAULT,
    RITUAL_MAX_INACTIVE_DAYS,
    push_rail_on,
)
from services import scheduler_service as ss

# её две строки + рельсы, которые дампом 13.11 НЕ были осуждены
ON_RAILS = {'life_events', 'rituals', 'day1_hook', 'daily_gift', 'scenario_cards',
            'first_minutes'}
# осуждённый шум: ни один не входит в список по умолчанию
OFF_RAILS = {'proactive', 'partner_nudge', 'random_gifts', 'daily_compatibility',
             'whats_new', 'donation_reminder', 'first_offer', 'trial_followup',
             'heavy_offer', 'paid_day1', 'renewal_care'}
# каждый джоб, который НАЧИНАЕТ разговор, регистрируется только по имени
PUSH_JOBS = tuple(sorted(ON_RAILS | OFF_RAILS))


class _Jobs:
    """подставной планировщик: интересуют только id зарегистрированных задач"""

    def __init__(self):
        self.ids = []

    @property
    def running(self):
        return True

    def add_job(self, _func, _trigger=None, **kw):
        self.ids.append(kw.get('id'))

    def start(self):
        pass


def _registered(monkeypatch, *, rails=None, master=None):
    jobs = _Jobs()
    monkeypatch.setattr(ss, 'scheduler', jobs)
    if rails is not None:
        monkeypatch.setattr(config, 'PUSH_RAILS', set(rails))
    if master is not None:
        monkeypatch.setattr(ss, 'MARKETING_PUSH_ENABLED', master)
    monkeypatch.setattr(ss, 'RITUALS_ENABLED', True, raising=False)
    monkeypatch.setattr(ss, 'LIFE_EVENTS_ENABLED', True, raising=False)
    ss.start_scheduler(None)
    return set(jobs.ids)


def test_the_default_list_names_exactly_the_rails_he_allowed():
    assert MARKETING_PUSH_ENABLED is True
    assert PUSH_RAILS == {r.strip() for r in PUSH_RAILS_DEFAULT.split(',') if r.strip()}
    assert push_rail_on('rituals') and push_rail_on('life_events')
    assert push_rail_on('  Rituals ')          # регистр и пробелы — не повод темноты
    for name in OFF_RAILS:
        assert not push_rail_on(name), name
    assert not push_rail_on('') and not push_rail_on(None)


def test_a_rail_outside_the_list_never_gets_a_job(monkeypatch):
    ids = _registered(monkeypatch)
    for name in ON_RAILS:
        assert name in ids, name
    for name in OFF_RAILS:
        if name == 'donation_reminder':        # там ещё и ссылка нужна
            continue
        assert name not in ids, name
    assert 'partner_nudge' not in ids           # приёмка ТЗ


def test_the_master_switch_still_kills_the_block_but_not_her_lines(monkeypatch):
    ids = _registered(monkeypatch, master=False)
    assert 'rituals' in ids
    for name in ON_RAILS | OFF_RAILS:
        if name != 'rituals':
            assert name not in ids, name


def test_her_morning_line_is_gated_by_the_list_alone(monkeypatch):
    assert 'rituals' not in _registered(monkeypatch, rails={'life_events'})
    assert 'life_events' not in _registered(monkeypatch, rails={'rituals'})
    assert 'rituals' in _registered(monkeypatch, rails={'rituals'}, master=False)


def test_every_job_that_starts_a_conversation_is_named():
    src = inspect.getsource(ss.start_scheduler)
    for name in PUSH_JOBS:
        assert f"push_rail_on('{name}')" in src, name


def test_the_ghost_window_now_reaches_three_weeks():
    # человек, вернувшийся на 11–20 день, раньше не получал ничего
    assert PROACTIVE_MAX_INACTIVE_DAYS == 21
    assert RITUAL_MAX_INACTIVE_DAYS == 14
    assert LIFE_EVENTS_ACTIVE_WINDOW_DAYS == 30
    # перебивки: не по первой же встрече, но и не раз в сутки
    assert INTERRUPT_MAX_PER_DAY == 2 and INTERRUPT_MIN_LEVEL == 2


def test_a_young_account_gets_her_more_often_than_a_settled_one():
    assert (LIFE_EVENTS_YOUNG_ACCOUNT_HOURS, LIFE_EVENTS_YOUNG_SILENCE_HOURS,
            LIFE_EVENTS_YOUNG_MAX_PER_DAY) == (72, 1.5, 4)
    assert LIFE_EVENTS_SILENCE_HOURS == 2 and LIFE_EVENTS_MAX_PER_DAY == 3
    body = inspect.getsource(ss._life_events)
    assert 'young = account_hours < LIFE_EVENTS_YOUNG_ACCOUNT_HOURS' in body
    assert 'silence_need = LIFE_EVENTS_YOUNG_SILENCE_HOURS if young' in body
    assert 'per_day = LIFE_EVENTS_YOUNG_MAX_PER_DAY if young' in body
