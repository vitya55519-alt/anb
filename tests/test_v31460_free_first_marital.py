"""V3.146.0: the FIRST «💍 Семейное положение» change is free for every user —
existing accounts included — and every later one still costs 500 🍑."""
import os

os.environ.setdefault('TELEGRAM_TOKEN', '123:abc')
os.environ.setdefault('GEMINI_API_KEY', 'x')

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_price_is_a_pure_decision():
    from types import SimpleNamespace
    from config import MARITAL_CHANGE_PEACHES
    from services import webapp_service as ws
    assert MARITAL_CHANGE_PEACHES == 500  # V3.65.0: ×100
    assert ws.marital_price(False) == 0  # the free change is still waiting
    assert ws.marital_price(True) == MARITAL_CHANGE_PEACHES
    assert ws.marital_price(None) == 0  # no user row yet = never changed
    assert ws.marital_price(SimpleNamespace(marital_change_free_used=False)) == 0
    assert ws.marital_price(SimpleNamespace(marital_change_free_used=True)) == 500


def test_flag_column_boots_on_a_fresh_db():
    from sqlalchemy import inspect
    from models.app_models import User
    from services.db import SessionLocal, engine, init_db
    from services.user_service import ensure_user
    assert hasattr(User, 'marital_change_free_used')
    init_db()
    assert 'marital_change_free_used' in {c['name'] for c in inspect(engine).get_columns('users')}
    uid = ensure_user(9914600)
    with SessionLocal() as s:
        assert s.get(User, uid).marital_change_free_used is False


def test_payload_carries_his_own_price():
    from models.app_models import User
    from services import webapp_service as ws
    from services.db import SessionLocal
    from services.user_service import ensure_user
    uid = ensure_user(9914601)
    with SessionLocal() as s:
        s.get(User, uid).marital_change_free_used = False
        s.commit()
    free = ws.api_characters(9914601)
    assert free and all(c['marital_price'] == 0 for c in free)
    with SessionLocal() as s:
        s.get(User, uid).marital_change_free_used = True
        s.commit()
    paid = ws.api_characters(9914601)
    assert paid and all(c['marital_price'] == 500 for c in paid)
    # the constant no longer leaks into the character payload
    assert "'marital_price': MARITAL_CHANGE_PEACHES," not in WEBAPP_SVC
    assert "price_marital = marital_price(user)" in WEBAPP_SVC
    assert "'marital_price': price_marital," in WEBAPP_SVC


def test_flag_burns_only_on_a_real_change():
    fn = MAIN[MAIN.index('async def _webapp_api_chat_marital('):MAIN.index('async def _webapp_api_marital_arc(')]
    same = fn.index("return None  # same pick again: free, nothing changes")
    decide = fn.index('free_change = MARITAL_CHANGE_PEACHES > 0 and webapp_service.marital_price(owner) == 0')
    refuse = fn.index("if not spend_peaches(telegram_id, MARITAL_CHANGE_PEACHES):")
    burn = fn.index('owner.marital_change_free_used = True')
    commit = fn.index('session.commit()')
    # nothing is asked, spent or burned while the pick changes nothing; the
    # refusal returns before the flag is written, both land in ONE commit.
    assert same < decide < refuse < burn < commit
    assert "if free_change and owner is not None:" in fn and "return 'peaches'" in fn
    # V3.59.6 pins: the charge line and the admin exemption stay as they were
    assert 'if MARITAL_CHANGE_PEACHES and not free_change and telegram_id not in ADMIN_TELEGRAM_IDS:' in fn
    assert 'row.marital_status = new_value' in fn


def test_answer_still_shares_the_next_price_and_the_402_shape():
    fn = MAIN[MAIN.index('async def _webapp_api_chat_marital('):MAIN.index('async def _webapp_api_marital_arc(')]
    assert "next_price['value'] = webapp_service.marital_price(owner)" in fn
    assert "**({'marital_price': next_price['value']} if next_price else {})" in fn
    assert "'error': 'peaches', 'price': MARITAL_CHANGE_PEACHES," in fn
    # V3.146.0: nothing else in the bot charges for her status — one price site.
    assert MAIN.count('spend_peaches(telegram_id, MARITAL_CHANGE_PEACHES)') == 1


def test_free_change_is_written_in_every_language():
    assert INDEX.count('marital_free:') == 8  # every language in Settings
    en = INDEX[INDEX.index('const L_EN = {'):INDEX.index('const L_RU = {')]
    ru = INDEX[INDEX.index('const L_RU = {'):INDEX.index('const L_OV = {')]
    ov = INDEX[INDEX.index('const L_OV = {'):]
    tail = ov.index('\nconst L =')
    assert "marital_free: 'free'," in en and "marital_free: 'бесплатно'," in ru
    keys = ['es', 'it', 'fr', 'zh', 'ja', 'bn']
    cuts = sorted(ov.index('\n  %s: {' % k) for k in keys)
    blocks = [ov[a:b] for a, b in zip(cuts, cuts[1:] + [tail])]
    assert len(blocks) == 6
    for block, (key, word) in zip(blocks, (('es', 'gratis'), ('it', 'gratis'), ('fr', 'gratuit'),
                                           ('zh', '免费'), ('ja', '無料'), ('bn', 'ফ্রি'))):
        assert key in block and "marital_free: '%s'," % word in block


def test_app_shows_free_and_never_confirms_a_free_change():
    render = INDEX[INDEX.index('function renderMarital(c)'):INDEX.index('async function loadMaritalArc(')]
    assert "price ? (L.marital_change + ' · ' + price + ' 🍑') : (L.marital_change + ' · ' + L.marital_free)" in render
    ask = render.index("if (!price) { go(); return; }")
    assert ask < render.index("const q = L.marital_confirm")  # 0 🍑: sent, no dialog
    choose = INDEX[INDEX.index('async function chooseMarital('):INDEX.index('async function choosePersona(')]
    assert "if (typeof j.marital_price === 'number') { c.marital_price = j.marital_price; renderMarital(c); }" in choose
    assert "if (r.status === 402) { c.marital = prev; renderMarital(c); toast(L.marital_no_peaches); showTab('shop'); return; }" in choose
