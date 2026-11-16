"""V3.167.1 (владелец, 16.11): «250 персиков раздеть» и «на одно фото можно заработать».

Цена откровенного кадра стала 250 🍑 — одна на раздевание, «Наедине», косплей и
фетиш, как договаривались в V3.165.0. И купленный персик перестаёт быть единственным
ключом: один «Раздеть» в сутки он вправе оплатить заработанными персиками (задания,
серия, канал), чтобы попробовать разблокировку без кошелька. Всё остальное — видео,
обычные фото, черновик, подарки — остаётся на купленных, а лимитов бесплатных
рендеров этот релиз не добавляет.
"""
import inspect
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
from services import payments as P

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')

MSK = timezone(timedelta(hours=3))


def _tid() -> int:
    return 816710000 + uuid.uuid4().int % 99999


def _user(**bal) -> int:
    """Аккаунт с нужными кошельками: bought — купленные, bonus — заработанные."""
    from services.user_service import ensure_user
    tid = _tid()
    ensure_user(tid, 'V')
    if bal.get('bought'):
        P.grant_photo_credits(tid, bal['bought'], f'bought{uuid.uuid4().hex[:8]}', bonus=False)
    if bal.get('bonus'):
        P.grant_photo_credits(tid, bal['bonus'], f'bonus{uuid.uuid4().hex[:8]}')
    return tid


# ── Блок 1: цена ─────────────────────────────────────────────────────────────

def test_the_frame_now_costs_250_and_is_still_one_price_for_everything():
    assert config.EXPLICIT_PHOTO_PEACH_COST == 250
    for alias in (config.UNDRESS_PEACH_COST, config.PRIVATE_PHOTO_PEACH_COST,
                  config.COSPLAY_PHOTO_PEACH_COST):
        assert alias == config.EXPLICIT_PHOTO_PEACH_COST
    # 250 🍑 ≈ 25 ₽ (пак 1000 🍑 стоит 99 ₽): кадр за ~$0.04 по-прежнему в прибыли,
    # покупку персиков не трогали
    rubles = config.UNDRESS_PEACH_COST / config.PEACH_SCALE * (config.PEACH_PACK_10_RUB / 10)
    assert 20 <= rubles <= 30, rubles


def test_the_price_lives_in_one_constant_and_the_app_reads_it_from_the_server():
    assert 'EXPLICIT_PHOTO_PEACH_COST = _peaches("EXPLICIT_PHOTO_PEACH_COST", 250)' in CONFIG
    # в SPA нет ни одной зашитой цифры: ценник приходит из /me и из чипа
    assert "PP('undress')" in INDEX and 'ME.undress_peaches' in INDEX
    assert "' · 300 🍑'" not in INDEX


# ── Блок 2: заработанный слот ────────────────────────────────────────────────

def test_earned_peaches_open_exactly_one_frame_a_day():
    tid = _user(bonus=300)
    assert P.bonus_photo_open(tid)
    assert P.spend_photo_peaches(tid, config.UNDRESS_PEACH_COST) == 'bonus'
    assert P.get_bonus_peaches(tid) == 50
    # второй тап в тот же день: слот занят, купленных нет — кадр закрыт
    assert not P.bonus_photo_open(tid)
    assert P.spend_photo_peaches(tid, config.UNDRESS_PEACH_COST) == ''
    assert P.get_bonus_peaches(tid) == 50


def test_bought_peaches_are_spent_first_and_the_earned_slot_survives():
    tid = _user(bought=300, bonus=300)
    assert P.spend_photo_peaches(tid, config.UNDRESS_PEACH_COST) == 'paid'
    assert P.get_paid_peaches(tid) == 50 and P.get_bonus_peaches(tid) == 300
    # слот не потрачен зря: когда купленные кончились, кадр снова доступен
    assert P.photo_peaches_ready(tid, config.UNDRESS_PEACH_COST)
    assert P.spend_photo_peaches(tid, config.UNDRESS_PEACH_COST) == 'bonus'
    assert P.get_bonus_peaches(tid) == 50


def test_nothing_is_charged_when_neither_wallet_covers_the_frame():
    tid = _user(bought=100, bonus=100)
    assert not P.photo_peaches_ready(tid, config.UNDRESS_PEACH_COST)
    assert P.spend_photo_peaches(tid, config.UNDRESS_PEACH_COST) == ''
    assert P.get_paid_peaches(tid) == 100 and P.get_bonus_peaches(tid) == 100


def test_yesterdays_earned_frame_does_not_burn_todays_slot():
    from sqlalchemy import update
    from services.db import SessionLocal
    from models.app_models import User
    tid = _user(bonus=500)
    assert P.spend_photo_peaches(tid, config.UNDRESS_PEACH_COST) == 'bonus'
    assert not P.photo_peaches_ready(tid, config.UNDRESS_PEACH_COST)
    yesterday_msk = datetime.now(MSK).date() - timedelta(days=1)
    stamp = datetime.combine(yesterday_msk, datetime.min.time(), tzinfo=MSK) - timedelta(hours=3)
    with SessionLocal() as s:
        s.execute(update(User).where(User.telegram_id == str(tid))
                  .values(bonus_photo_at=stamp.replace(tzinfo=None)))
        s.commit()
    assert P.bonus_photo_open(tid)
    assert P.photo_peaches_ready(tid, config.UNDRESS_PEACH_COST)
    assert P.spend_photo_peaches(tid, config.UNDRESS_PEACH_COST) == 'bonus'


def test_the_day_rolls_over_at_moscow_midnight_not_at_utc_midnight():
    start = P._bonus_photo_day_start(datetime(2026, 11, 16, 0, 30, tzinfo=MSK))
    assert start == datetime(2026, 11, 15, 21, 0)          # 00:30 МСК 16-го = 21:00 UTC 15-го
    assert P._bonus_photo_day_start(datetime(2026, 11, 16, 23, 59, tzinfo=MSK)) == start


def test_the_flag_puts_the_old_rule_back(monkeypatch):
    monkeypatch.setattr(P, 'BONUS_PHOTO_ENABLED', False)
    tid = _user(bonus=300)
    assert not P.bonus_photo_open(tid)
    assert not P.photo_peaches_ready(tid, config.UNDRESS_PEACH_COST)
    assert P.spend_photo_peaches(tid, config.UNDRESS_PEACH_COST) == ''
    assert P.get_bonus_peaches(tid) == 300


def test_the_slot_is_taken_inside_the_update_so_two_taps_cannot_both_pass():
    src = inspect.getsource(P.spend_photo_peaches)
    assert 'or_(User.bonus_photo_at.is_(None)' in src
    assert 'bonus_photo_at=datetime.now' in src
    assert 'rowcount == 1' in src


# ── Блок 3: слот — только «Раздеть» ──────────────────────────────────────────

def test_only_the_undress_door_uses_the_earned_slot():
    assert MAIN.count('spend_photo_peaches(telegram_id') == 2
    assert MAIN.count('photo_peaches_ready(telegram_id') == 4
    assert 'photo_peaches_ready(telegram_id, UNDRESS_PEACH_COST)' in MAIN
    assert 'spend_photo_peaches(telegram_id, UNDRESS_PEACH_COST)' in MAIN
    # всё остальное — как раньше: рендер оплачивают только купленные персики
    assert 'spend_peaches(telegram_id, EXPLICIT_PHOTO_PEACH_COST, paid_only=True)' in MAIN
    assert 'spend_peaches(telegram_id, CHAT_PHOTO_PEACH_COST, paid_only=True)' in MAIN
    assert 'if get_paid_peaches(telegram_id) < EXPLICIT_PHOTO_PEACH_COST:' in MAIN


def test_the_bonus_wallet_still_does_not_pay_for_a_plain_chat_photo():
    # единственная строка, где это сказано ему в лицо, осталась правдой
    assert 'только купленные персики, бонусные на фото не идут' in MAIN


def test_the_app_tells_him_the_earned_slot_exists_in_both_languages():
    assert 'раз в сутки — за один кадр «Раздеть»' in INDEX
    assert 'once a day they pay for one «Undress» photo' in INDEX
    assert 'Фото и видео за купленные персики.' not in INDEX
    assert 'Photos and videos take bought peaches.' not in INDEX


def test_the_stamp_column_is_declared_for_the_auto_migration():
    from models.app_models import User
    assert 'bonus_photo_at' in User.__table__.columns
