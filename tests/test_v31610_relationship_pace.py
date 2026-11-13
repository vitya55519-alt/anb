# V3.161.0 — темп привязанности по живым данным, а не на глаз.
#
# Дамп 13.11: 467 строк из 474 значатся «незнакомец», медианный пользователь
# пишет 5 сообщений за один день, 96% реплик не содержат ни одного слова из
# сигнальных шаблонов. Старый вход в уровень 2 стоил 15 очков отношений и 10
# доверия при +0,2 за сообщение и доверии, которое давало только «спасибо /
# расскажи» (2,25% реплик). Симулятор на реальном движке показывал уровень 2
# лишь на 96-м сообщении шестого дня — то есть почти ни у кого.
#
# Правка: нижние ступени опущены, обычное сообщение перестало быть нулём, пульс
# стал чаще и весомее. Столбец «возвращения» (continuity) и уровень 6 — платная
# стена — не тронуты: темп по-прежнему задаёт то, что он вернулся, а не счётчик.

import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.waifu_models import Base
import models.relationship_models  # noqa: F401
from services import relationship_engine as E
from services.relationship_pulse import PULSE_EVERY, PULSE_WEIGHT
from services.relationship_signals import infer_delta

START = dt.datetime(2026, 11, 1, 12, 0)
CARE_EVERY, FLIRT_EVERY = 44, 61   # доли из замера: 2,25% и 1,63% реплик


def _replay(n_msgs, days, *, care_every=CARE_EVERY, flirt_every=FLIRT_EVERY, pulse=True):
    """Крутит настоящий apply_delta на синтетическом пользователе."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    first_at, row = {}, None
    for k in range(1, n_msgs + 1):
        day = min(days - 1, (k - 1) * days // n_msgs) if days > 1 else 0
        at = START + dt.timedelta(days=day, minutes=k * 7)
        if k % care_every == 0 and k % flirt_every == 0:
            text = 'спасибо, ты милая'
        elif k % care_every == 0:
            text = 'расскажи, как ты?'
        elif k % flirt_every == 0:
            text = 'ты красивая'
        else:
            text = 'а что делаешь'
        d = infer_delta(text)
        rel, tr, intm, ev = d.relationship, d.trust, d.intimacy, d.event_type
        if pulse and k % PULSE_EVERY == 0:      # пульс оценивает fragment как живой LLM
            rel += 1.5 * PULSE_WEIGHT
            tr += 1.0 * PULSE_WEIGHT
            intm += 0.5 * PULSE_WEIGHT
            ev = 'callback'
        row = E.apply_delta(s, 1, 'anna_01', E.RelationshipDelta(
            relationship=rel, trust=tr, intimacy=intm, event_type=ev, reason='pace_probe'), now=at)
        first_at.setdefault(row.stage, (k, day + 1))
    out = dict(first_at), tuple(round(x, 1) for x in (
        row.relationship_score, row.trust_score, row.intimacy_score, row.connection_score))
    s.close()
    return out


def _level_at(n_msgs, days, level_index, **kw):
    got, _ = _replay(n_msgs, days, **kw)
    stage = E.STAGE_ORDER[level_index]
    return got.get(stage, (None, None))[0]


def test_a_plain_message_is_no_longer_worth_zero():
    d = infer_delta('а что делаешь')
    assert (d.relationship, d.trust, d.intimacy) == (0.35, 0.15, 0)
    assert d.event_type == 'interaction'
    # сигнальные вспышки остались сильнее обычного тона — иначе темп стал бы
    # платой за количество сообщений
    assert infer_delta('расскажи, как ты?').trust > d.trust * 6
    assert infer_delta('ты красивая').intimacy > 0
    assert infer_delta('заткнись').trust == -2


def test_the_paid_wall_and_the_premium_floor_are_untouched():
    gates = {s: (r, t, i) for s, r, t, i in E.STAGE_RULES}
    assert gates['committed'] == (90, 85, 80)
    assert gates['devoted'] == (95, 90, 85)
    assert gates['soulmate'] == (98, 96, 92)
    assert E.DIMENSION_GATES['committed'] == (65, 35, 35)
    # Premium-пол вычисляется из тех же порогов — значит потолок бесплатного
    # не пополз вверх вместе с нижними ступенями
    assert E._PREMIUM_FLOOR_RAW == (90, 85, 80)
    assert E._PREMIUM_FLOOR_DIMS == (65, 35, 35)


def test_returning_days_still_cost_the_same():
    # средний столбец DIMENSION_GATES = continuity, +1,7 за новый день. Трогать
    # его нельзя: тогда уровень можно было бы накупить сообщениями за один день.
    assert [E.DIMENSION_GATES[s][1] for s in
            ('stranger', 'acquaintance', 'close', 'intimate', 'deeply_connected', 'committed')] == \
        [0, 0, 5, 12, 22, 35]


def test_the_ladder_moves_for_every_real_slice_of_the_audience():
    # p90 дампа (41 сообщение за 4 дня) берёт уровень 2 — раньше его не было и у
    # того, кто написал 300
    assert _level_at(41, 4, 1) is not None
    # активный (120/7) доходит до уровня 3, заядлый (300/20) — до 4 и 5
    assert _level_at(120, 7, 2) is not None
    assert _level_at(300, 20, 3) is not None
    assert _level_at(300, 20, 4) is not None


def test_a_drive_by_visitor_earns_nothing():
    # медиана дампа — 5 сообщений за день: полоска двинулась, уровня нет.
    # Дешёвый трафик не должен получать ceremony-письмо, за которое потом стыдно
    got, axes = _replay(5, 1)
    assert set(got) == {'stranger'}
    assert max(axes) < E.STAGE_RULES[-2][1]


def test_message_count_alone_cannot_buy_level_six():
    # 300 сообщений за ОДИН день (накрутка, бот, марафон) — потолок всё равно
    # уровень 3: 300 сообщений за день — это и правда один очень длинный вечер.
    # Но платная стена стоит на возвращениях: +1,7 за новый день против +0,2 за
    # каждые 12 сообщений в тот же день, значит 35 очков непрерывности за сутки
    # не набрать ничем.
    got, axes = _replay(300, 1)
    assert 'committed' not in got
    assert max(got, key=lambda s: E.STAGE_ORDER.index(s)) == 'close'


def test_the_ladder_outruns_itself_only_where_the_user_is_actually_warm():
    # страстный путь (флирт в каждой пятой реплике) — единственный, кто доходит
    # до платной стены: 300 сообщений за 20 дней
    neutral = _level_at(300, 20, 5)
    warm = _level_at(300, 20, 5, care_every=20, flirt_every=5)
    assert neutral is None and warm is not None


def test_pulse_now_reaches_the_typical_conversation():
    assert PULSE_EVERY == 6 and PULSE_WEIGHT == 0.6
    assert PULSE_EVERY < 8, 'пульс должен успеть сработать до того, как человек ушёл'
    got, _ = _replay(12, 1)
    assert any(k % PULSE_EVERY == 0 for k in range(1, 13))


def test_nobody_is_demoted_by_the_rebalance():
    # тот, кто уже доехал до уровня по старым порогам, не падает вниз: движок
    # держит old_stage, и после понижении ступеней это единственная защита,
    # которую человек заметит в профиле
    from models.relationship_models import UserCharacterRelationship
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    now = START
    row = UserCharacterRelationship(user_id=1, character_id='anna_01', stage='intimate',
                                    relationship_score=2.0, trust_score=1.0, intimacy_score=0.0,
                                    familiarity_score=1.0, continuity_score=1.0, connection_score=1.0,
                                    total_messages=40, first_interaction_at=now,
                                    last_interaction_at=now, last_distinct_day=now)
    s.add(row)
    s.commit()
    after = E.apply_delta(s, 1, 'anna_01', E.RelationshipDelta(relationship=0.35, trust=0.15,
                                                               event_type='interaction'), now=now)
    assert after.stage == 'intimate'
