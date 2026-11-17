"""V3.167.5 §9–§10 (владелец ТЗ «включить её жизнь», Фогель, 16.11).

§9 — аналитика. Раньше «она написала первой» было размазано по двадцати четырём
именам событий, отказ губернатора жил только в логе процесса, а D1 считался по
всем подряд — включая 354 аккаунта, которые ни разу не написали. Теперь: одна
каноническая лента `push_sent{rail}` (выводится из физического имени, ни один
из 24 вызовов трогать не пришлось), `push_denied{rail,reason}` — но не чаще
раза на (аккаунт, рельс, причина) в сутки, иначе сканер залил бы журнал;
её день видно отдельной строкой (`life_event_shown`) и его же ответ
(`life_event_replied`), плюс `opening_shown`, `streak_tick`, `streak_freeze`,
`digest_shown`. D1/D7 показываются и по когорте «дошёл до 12+ своих сообщений»
— отдельно от бленда, как просит ТЗ.

§10 — миграции. Идемпотентность держится на журнале `app_migrations`: имя =
первичный ключ, поэтому второй старт ничего не повторяет; ALTER собираются в
одну транзакцию на таблицу; в лог попадает что добавлено и сколько строк в
таблице. Обратная миграция лежит текстом в `BUILD_CHANGES_V3_167_5.md` —
исполняемый `DROP COLUMN` в репозитории был бы jednorазовой гранатой, а откат
релиза владелец всегда делал флагом.

Экономику не трогаем: ни одной новой бесплатной генерации, цену персиков и
покупку не трогали (см. `services/chat_photo_allowance`).
"""
import uuid
from pathlib import Path

import config
from models.app_models import Message, ProductEvent
from services import analytics_service as AN
from services import life_backlog as LB
from services import push_governor as G
from services.db import SessionLocal, _add_missing_columns, _index_analytics_stream, engine

import logging
from sqlalchemy import inspect as sa_inspect, select, text

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
LIFE = (ROOT / 'services' / 'life_event_service.py').read_text(encoding='utf-8')
LIVE = (ROOT / 'services' / 'live_situation_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')
NOTE = (ROOT / 'BUILD_CHANGES_V3_167_5.md').read_text(encoding='utf-8')


def _uid() -> int:
    from services.user_service import ensure_user
    return ensure_user(817250000 + uuid.uuid4().int % 99999, 'Аня')


def _char() -> str:
    return 'v31675_' + uuid.uuid4().hex[:6]


def _line(uid, char, role, text, origin=None, ago=0):
    import datetime as dt
    from services.memory_service import save_message
    mid = save_message(uid, char, role, text, origin=origin)
    if ago:
        with SessionLocal() as s:
            row = s.get(Message, int(mid))
            row.created_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(hours=ago)
            s.commit()
    return int(mid)


def _events(uid, name):
    with SessionLocal() as s:
        return s.scalars(select(ProductEvent).where(
            ProductEvent.user_id == int(uid), ProductEvent.event_name == name)).all()


# ── Блок 1: чей ход в диалоге ────────────────────────────────────────────────

def test_a_line_she_wrote_first_carries_its_rail():
    assert 'origin: Mapped[str | None]' in (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
    assert 'origin=origin' in (ROOT / 'services' / 'memory_service.py').read_text(encoding='utf-8')
    # весь scheduler идёт через одну точку — и по умолчанию это её ход
    assert 'def _to_app_chat(uid, tg_id, char_id, text, shot=None, origin=PUSH_ORIGIN, actions=None)' in SCHED
    assert SCHED.count('_to_app_chat(') > SCHED.count('origin=LIFE_ORIGIN')   # остальные — 'push'
    assert 'origin=LIFE_ORIGIN' in SCHED and 'origin=LIFE_ORIGIN' in LIVE


def test_her_answer_to_him_is_not_an_unanswered_push():
    uid, char = _uid(), _char()
    _line(uid, char, 'user', 'привет')
    _line(uid, char, 'assistant', 'о, ты наконец')          # обычный ответ, origin=NULL
    assert LB.unanswered(uid, char) == []
    assert not LB.is_capped(uid, char)
    for i in range(config.LIFE_EVENTS_UNANSWERED_MAX):
        _line(uid, char, 'assistant', f'день {i}', origin=LB.LIFE_ORIGIN)
    assert LB.is_capped(uid, char)


def test_the_digest_is_hers_too():
    src = (ROOT / 'services' / 'life_backlog.py').read_text(encoding='utf-8')
    # The message and daily dedupe marker now commit in the same transaction.
    assert 'content=text, origin=DIGEST_ORIGIN)' in src
    assert LB.PUSHED_ORIGINS == (LB.PUSH_ORIGIN, LB.LIFE_ORIGIN, LB.DIGEST_ORIGIN)


def test_her_day_answered_is_counted_before_he_writes():
    uid, char = _uid(), _char()
    _line(uid, char, 'user', 'сплю', ago=6)
    _line(uid, char, 'assistant', 'я тут суп ела', origin=LB.LIFE_ORIGIN, ago=3)
    assert LB.note_replied(uid, char) == 1
    assert _events(uid, 'life_event_replied'), 'события нет — DoD «ответы ≥12%» нечем мерить'
    # после того как его строка легла, отвечать не на что
    _line(uid, char, 'user', 'а я спал')
    assert LB.note_replied(uid, char) == 0


def test_a_marketing_push_is_not_her_day():
    uid, char = _uid(), _char()
    _line(uid, char, 'assistant', 'ты где', origin=LB.PUSH_ORIGIN, ago=3)
    assert LB.note_replied(uid, char) == 0               # proactive_replied мерит это
    assert LB.is_capped(uid, char) is False              # но в накоплении считается


# ── Блок 2: одна лента вместо двадцати четырёх имён ──────────────────────────

def test_push_sent_is_derived_not_threaded_through_twenty_four_calls():
    uid = _uid()
    AN.track_event(uid, 'retention_push_sent', metadata={'hours_inactive': 48})
    rows = _events(uid, AN.PUSH_SENT_EVENT)
    assert len(rows) == 1 and '"rail": "marketing"' in rows[0].metadata_json
    assert '"kind": "retention_push_sent"' in rows[0].metadata_json
    assert '"hours_inactive": 48' in rows[0].metadata_json    # метаданные не потерялись
    AN.track_event(uid, 'chat_user_message')
    assert len(_events(uid, AN.PUSH_SENT_EVENT)) == 1         # его ход — не её пуш


def test_the_canonical_names_never_spend_the_day_budget():
    for alias in (AN.PUSH_SENT_EVENT, G.DENIAL_EVENT, 'life_event_shown', 'digest_shown'):
        assert alias not in G.PUSH_EVENTS, f'{alias} в PUSH_EVENTS удваивает норму дня'
        for names in G.FAMILY_EVENTS.values():
            assert alias not in names
    assert AN.PUSH_SENT_EVENT == 'push_sent' and G.DENIAL_EVENT == 'push_denied'


def test_the_refusal_is_visible_and_quiet():
    uid = _uid()
    assert len(_events(uid, G.DENIAL_EVENT)) == 0
    orig = G.in_quiet_hours
    G.in_quiet_hours = lambda hour: True
    try:
        assert G.allow_push(uid, 'UTC', family='life') == (False, 'night')
        assert G.allow_push(uid, 'UTC', family='life') == (False, 'night')
    finally:
        G.in_quiet_hours = orig
    rows = _events(uid, G.DENIAL_EVENT)
    assert len(rows) == 1, 'часовой сканер пишет отказы пачкой — журнал тонет в шуме'
    assert '"rail": "life"' in rows[0].metadata_json and '"reason": "night"' in rows[0].metadata_json


def test_a_different_reason_is_a_different_number():
    uid = _uid()
    G._note_denial(uid, 'life', 'night')
    G._note_denial(uid, 'life', 'daily')
    assert len(_events(uid, G.DENIAL_EVENT)) == 2
    G._note_denial(0, 'life', 'night')            # без аккаунта писать некому
    assert len(_events(0, G.DENIAL_EVENT)) == 0


# ── Блок 3: события, которых не было вовсе ───────────────────────────────────

def test_the_first_move_the_streak_and_the_digest_have_names():
    assert "track_event(int(uid), 'opening_shown')" in MAIN
    gam = (ROOT / 'services' / 'gamification_service.py').read_text(encoding='utf-8')
    assert "'streak_tick'" in gam and "'streak_freeze'" in gam
    assert "'streak_freeze'" in (ROOT / 'services' / 'series_reward.py').read_text(encoding='utf-8')
    src = (ROOT / 'services' / 'life_backlog.py').read_text(encoding='utf-8')
    assert "'digest_shown'" in src and 'life_digest_sent' not in src       # имя из ТЗ, одно
    assert "'life_event_shown'" in SCHED and "'life_event_sent'" in SCHED  # старое кормит губернатора
    assert 'life_event_shown' not in LIFE                                  # рельс пишет scheduler, не сервис


def test_the_streak_number_is_once_per_day():
    gam = (ROOT / 'services' / 'gamification_service.py').read_text(encoding='utf-8')
    body = gam[gam.index('def touch_activity('):gam.index('# Unlock streak achievements')]
    assert 'froze = False' in body and "if summary.get('new_streak_day'):" in body


# ── Блок 4: D1/D7 по когорте, которая дошла ──────────────────────────────────

def test_the_activation_threshold_is_the_tz_number():
    assert config.ACTIVATION_MIN_MESSAGES == 12
    uid, char = _uid(), _char()
    for i in range(11):
        _line(uid, char, 'user', f'{i}')
    with SessionLocal() as s:
        assert AN.activated_ids(s, [uid]) == set()
        _line(uid, char, 'user', '12')
        assert AN.activated_ids(s, [uid]) == {uid}
        assert AN.activated_ids(s, []) == set()


def test_blended_and_cohort_survive_one_pass():
    rates = AN.retention_cohorts((1, 3, 7))
    assert set(rates) == {1, 3, 7} and set(rates[1]) >= {'all', 'activated', 'cohort', 'activated_cohort'}
    assert AN.retention_split(1, activated_only=True, activated=set()) == 0.0
    # прежняя функция осталась и по-прежнему мерит любой свой ход, а не пуш:
    # на её исходный текст смотрит статический тест V3.59.0
    src = (ROOT / 'services' / 'analytics_service.py').read_text(encoding='utf-8')
    window = src[src.index('def _retention_rate('):src.index('def activated_ids(')]
    assert 'ProductEvent.event_name.in_(ACTIVE_EVENTS)' in window


def test_the_kitchen_shows_rails_and_the_cohort():
    snap = AN.admin_snapshot()
    assert 'rails' in snap and 'd1_retention_activated' in snap
    lines = AN.format_rail_lines(snap['rails'])
    assert any('её ход за сутки' in s for s in lines)
    assert any('надо ≥12%' in s for s in lines) and any('надо ≥70%' in s for s in lines)
    assert MAIN.count('format_rail_lines(') == 2                 # обе кухни: RU и EN
    assert 'd7_retention_activated' in MAIN
    assert snap['d1_retention'] <= 100.0 and snap['d1_retention_activated'] <= 100.0


def test_rail_activity_reads_the_canonical_stream():
    uid = _uid()
    AN.track_event(uid, 'life_event_sent', metadata={'when': 'evening'})
    AN.track_event(uid, 'ritual_morning_sent')
    G._note_denial(uid, 'marketing', 'daily')
    act = AN.rail_activity(1)
    assert act['sent_by_rail'].get('life', 0) >= 1 and act['sent_by_rail'].get('ritual', 0) >= 1
    assert act['held_by_reason'].get('marketing:daily', 0) >= 1
    assert act['cohort_30d'] >= 1


# ── Блок 5: миграции (§10) — идемпотентно, в транзакции, с логом ─────────────

def test_a_column_added_twice_is_added_once(caplog):
    col = '_probe_v31675'
    with engine.begin() as c:
        c.execute(text('CREATE TABLE IF NOT EXISTS probe_v31675 (id INTEGER PRIMARY KEY)'))
    caplog.set_level(logging.WARNING, logger='services.db')
    _add_missing_columns('probe_v31675', {col: 'INTEGER'})
    _add_missing_columns('probe_v31675', {col: 'INTEGER'})       # второй старт: уже есть
    assert 'probe_v31675: +' in caplog.text and 'rows=0' in caplog.text
    assert caplog.text.count(f'+{col}') == 1, 'повторный старт добавил колонку дважды'
    with SessionLocal() as s:
        marks = s.execute(text("SELECT COUNT(*) FROM app_migrations "
                               "WHERE name = 'schema:probe_v31675:_probe_v31675'")).scalar()
        assert marks == 1                                        # журнал = ровно одна запись


def test_the_journal_names_every_object_the_release_touched():
    body = DB[DB.index('def _add_missing_columns('):]
    assert 'with engine.begin() as conn:' in body
    assert '_mark_applied(conn, marker)' in body and '_already_applied(conn, marker)' in body
    assert 'def _index_analytics_stream(' in DB and '_index_analytics_stream()' in DB
    assert "SET lock_timeout" in DB, 'индекс не должен ждать блокировку вечно'
    # обычный CREATE INDEX на живой Postgres держит таблицу записанной всю
    # стройку — бот встаёт посреди дня. Postgres-ветка обязана быть CONCURRENTLY.
    idx_body = DB[DB.index('def _index_analytics_stream('):]
    assert 'CREATE INDEX CONCURRENTLY IF NOT EXISTS' in idx_body
    assert "isolation_level='AUTOCOMMIT'" in idx_body
    assert 'ix_product_events_name_created' in DB


def test_the_stream_index_is_idempotent():
    _index_analytics_stream()
    _index_analytics_stream()
    names = {i['name'] for i in sa_inspect(engine).get_indexes('product_events')}
    assert 'ix_product_events_name_created' in names


def test_the_reverse_migration_lives_in_the_repository():
    assert 'DROP INDEX IF EXISTS ix_product_events_name_created' in NOTE
    assert 'ALTER TABLE messages DROP COLUMN origin' in NOTE
    for name in ('push_sent', 'push_denied', 'life_event_shown', 'life_event_replied',
                 'opening_shown', 'streak_tick', 'streak_freeze', 'digest_shown'):
        assert name in NOTE, f'{name} не описан в BUILD_CHANGES — сверять откат не с чем'
    assert 'ACTIVATION_MIN_MESSAGES' in NOTE
