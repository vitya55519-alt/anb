"""V3.169: her-day reply count, character-selected event, renewal for Platega payers,
weekly report line, greeting stock, source tag."""
from datetime import datetime, timedelta, timezone

from models.app_models import Base, StarTransaction, Subscription, User
from services import renewal_care as rc
from services.db import SessionLocal, engine


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user():
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        u = User(telegram_id=str(int(_now().timestamp() * 1e6) % 10 ** 12), name='t')
        s.add(u); s.commit()
        return u.id, int(u.telegram_id)


def _pay(uid, product, at, days, provider='stars', charge=None):
    with SessionLocal() as s:
        charge = charge or f'{provider}:{uid}:{at.timestamp()}'
        s.add(StarTransaction(user_id=uid, transaction_type='purchase', product=product,
                              stars=0 if provider == 'platega' else 1, provider=provider,
                              telegram_charge_id=charge, created_at=at))
        s.add(Subscription(user_id=uid, plan='premium', status='active', started_at=at,
                           expires_at=at + timedelta(days=days), telegram_charge_id=charge))
        s.commit()


def test_platega_payer_gets_soon_and_ended():
    uid, tg = _user()
    _pay(uid, 'premium_month', _now() - timedelta(days=30) + timedelta(hours=20), 30, provider='platega')
    rows = [r for r in rc.candidates() if r[0] == uid]
    assert rows and rows[0][3] == 'soon' and rows[0][4] == 'premium_month'
    later = _now() + timedelta(hours=23)
    assert [r for r in rc.candidates(later) if r[0] == uid][0][3] == 'ended'


def test_admin_grant_after_a_paid_month_gets_nothing():
    uid, _ = _user()
    _pay(uid, 'premium_month', _now() - timedelta(days=60), 30, provider='platega')
    with SessionLocal() as s:
        s.add(Subscription(user_id=uid, plan='premium', status='active', stars_amount=0,
                           started_at=_now() - timedelta(days=29),
                           expires_at=_now() + timedelta(hours=10),
                           telegram_charge_id='admin_grant:123'))
        s.commit()
    assert not [r for r in rc.candidates() if r[0] == uid]


def test_weekly_report_limit_line_is_summed_not_glued():
    import inspect
    from services import weekly_report
    src = inspect.getsource(weekly_report)
    assert '+ ev(' not in src and 'ev_sum("chat_limit_wall", "chat_sleep_block")' in src


def test_life_reply_is_counted_once_per_tail(monkeypatch):
    from services import life_backlog as lb
    when = _now() - timedelta(hours=2)
    monkeypatch.setattr(lb, '_pushed', lambda uid, ch, limit=6: [('привет', when, lb.LIFE_ORIGIN)])
    uid, _ = _user()
    seen = []
    import services.analytics_service as an
    monkeypatch.setattr(an, 'track_event', lambda u, name, **kw: seen.append(name))
    assert lb.note_replied(uid, 'anna_01', via='tap') == 1
    from models.app_models import ProductEvent
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=uid, event_name='life_event_replied', created_at=_now()))
        s.commit()
    assert lb.note_replied(uid, 'anna_01') == 0


def test_note_replied_is_wired():
    import pathlib
    main = pathlib.Path('main.py').read_text()
    assert main.count('note_replied(') >= 2
    assert '_note_character_selected(telegram_id, character_id' in main


def test_private_photo_unlabeled_gets_private_tag():
    from services import spend_service as ss
    assert 'private_photo' in ss.SPEND_SOURCES
    import pathlib
    assert '_spicyapi_render_labeled' in pathlib.Path('services/private_photo_service.py').read_text()


# ── «Без цензуры» ────────────────────────────────────────────────────────────
def test_unlock_prices_are_env_driven_and_default_50():
    import config
    assert config.UNCENSORED_UNLOCK_RUB == 50 and config.UNCENSORED_UNLOCK_STARS == 50


def test_entitlement_premium_or_unlocked_only():
    from services import uncensored_unlock as uu
    user = type('U', (), {'uncensored_unlocked_at': None})()
    assert not uu.entitled(user, premium=False)
    assert uu.entitled(user, premium=True)
    user.uncensored_unlocked_at = datetime(2026, 1, 1)
    assert uu.entitled(user, premium=False)


def test_payment_unlocks_once_and_counts_rub_and_stars_apart():
    from services.payments import record_payment
    from models.app_models import ProductEvent
    uid, tg = _user()
    record_payment(tg, 'uncensored_unlock', 0, f'platega:u{uid}', provider='platega',
                   provider_payload='amount=50')
    record_payment(tg, 'uncensored_unlock', 0, f'platega:u{uid}', provider='platega',
                   provider_payload='amount=50')          # duplicate webhook
    with SessionLocal() as s:
        assert s.get(User, uid).uncensored_unlocked_at is not None
        rows = s.query(ProductEvent).filter_by(user_id=uid, event_name='uncensored_bought').all()
    assert len(rows) == 1 and '"currency": "RUB"' in rows[0].metadata_json
    uid2, tg2 = _user()
    record_payment(tg2, 'uncensored_unlock', 50, f'stars:u{uid2}')
    with SessionLocal() as s:
        row = s.query(ProductEvent).filter_by(user_id=uid2, event_name='uncensored_bought').one()
    assert '"currency": "XTR"' in row.metadata_json


def test_prompt_block_after_character_and_style_tail_last():
    from services import character_service as cs
    from services.uncensored_unlock import PROMPT_BLOCK
    ch = {'name': 'Анна', 'age': 26, 'personality': {}}
    p = cs.build_system_prompt(ch, 'rel', [], user_name='И', uncensored_block=PROMPT_BLOCK)
    assert p.index('ХАРАКТЕР') < p.index('[РЕЖИМ: БЕЗ ЦЕНЗУРЫ (18+)') < p.index('ГЛАВНОЕ ПРАВИЛО')
    assert 'только взрослые' in PROMPT_BLOCK            # the hard limits stay in the mode
    plain = cs.build_system_prompt(ch, 'rel', [], user_name='И')
    assert '[РЕЖИМ: БЕЗ ЦЕНЗУРЫ' not in plain
    for text in (p, plain):
        assert text.rstrip().endswith('но никогда не предлагай купить фото напрямую.')
        assert text.index('[СТИЛЬ И РИТМ ПЕРЕПИСКИ]') < text.index('[ПАМЯТЬ И ЭМОЦИОНАЛЬНАЯ ИНЕРЦИЯ]') \
            < text.index('[ПРИСУТСТВИЕ В МОМЕНТЕ]')


def test_wiring_of_the_unlock():
    import pathlib
    main = pathlib.Path('main.py').read_text()
    assert "payload=='uncensored_unlock'" in main and "payload == 'uncensored_unlock'" in main
    assert "'uncensored_unlock': 'uncensored_unlock'" in main
    assert 'uncensored_checkout' in main and "error': 'uncensored_locked'" in main
    assert 'uncensored_hint' in main
    from services import webapp_service
    ids = [p['id'] for p in webapp_service.api_invoice_products('ru')]
    assert 'uncensored_unlock' in ids
    rpt = pathlib.Path('services/weekly_report.py').read_text()
    assert 'uncensored_offer_shown' in rpt and 'uncensored_bought' in rpt
    assert 'Ну наконец-то ты убрал эти дурацкие рамки' in pathlib.Path('services/uncensored_unlock.py').read_text()
    html = pathlib.Path('webapp/index.html').read_text()
    assert 'unlockSheet' in html and 'Режим «Без цензуры» — сними все запреты' in html
