"""V3.114.0 — «👗 Гардероб»: clothes and room things he gives her for peaches."""
import random
from pathlib import Path

from services import wardrobe_service as wd
from services.db import engine
from models.app_models import Base

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
APP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def _uid():
    Base.metadata.create_all(engine)
    return random.randint(10**9, 2 * 10**9)


def test_catalog_prices_cover_the_try_on_render():
    from config import CHAT_PHOTO_PEACH_COST
    assert len({i.id for i in wd.ITEMS}) == len(wd.ITEMS)
    for i in wd.ITEMS:
        assert i.price > CHAT_PHOTO_PEACH_COST, i.id
        assert len(i.prompt) <= 200, i.id  # one short WARDROBE value, SpicyAPI 5000 cap stays safe
    assert wd.get('kitten').price == 2500 and wd.get('hoodie').price == 300


def test_grant_wears_lifts_mood_and_is_once_only():
    uid = _uid()
    assert wd.mood(uid, 'anna_01') == wd.MOOD_BASE
    assert wd.grant(uid, 'anna_01', 'sweater')
    assert not wd.grant(uid, 'anna_01', 'sweater')
    assert wd.worn_today(uid, 'anna_01').id == 'sweater'
    assert wd.mood(uid, 'anna_01') == wd.MOOD_BASE + wd.MOOD_WEAR_BONUS
    # another girl has nothing
    assert wd.owned_ids(uid, 'lana_01') == []


def test_mood_never_drops_below_calm():
    st = wd.WardrobeState(mood=90, mood_at=wd.utcnow() - wd.timedelta(hours=500))
    assert wd._mood_now(st) == wd.MOOD_BASE
    assert wd.mood_label(wd.MOOD_BASE) == 'спокойная'


def test_wear_only_owned_and_photo_overrides():
    uid = _uid()
    assert not wd.wear(uid, 'anna_01', 'gown')
    wd.grant(uid, 'anna_01', 'sundress')
    wd.grant(uid, 'anna_01', 'pendant')
    wd.grant(uid, 'anna_01', 'lights')
    o = wd.photo_overrides(uid, 'anna_01', 'cafe', 'day_casual')
    assert o['clothing'] == wd.get('sundress').prompt
    assert 'heart pendant' in o['accessory']
    assert 'room' not in o  # a cafe is not her room
    o = wd.photo_overrides(uid, 'anna_01', 'home', 'home')
    assert 'fairy lights' in o['room']
    assert wd.photo_overrides(uid, 'anna_01', 'restaurant', 'evening').get('clothing') is None
    assert wd.wear(uid, 'anna_01', '')
    assert wd.worn_today(uid, 'anna_01') is None


def test_chat_line_mentions_gifts_and_never_begs():
    uid = _uid()
    assert wd.chat_line(uid, 'anna_01') == ''
    wd.grant(uid, 'anna_01', 'hoodie')
    wd.grant(uid, 'anna_01', 'kitten')
    line = wd.chat_line(uid, 'anna_01')
    assert 'его худи' in line and 'котёнок' in line and 'Никогда не проси новых подарков' in line
    assert wd.set_pet_name(uid, 'anna_01', 'Пушок<script>') == 'Пушокscript'
    assert 'котёнок Пушокscript' in wd.chat_line(uid, 'anna_01')


def test_adult_items_need_premium_and_18():
    assert not wd.can_buy_adult(premium=False, adult=True)
    assert not wd.can_buy_adult(premium=True, adult=False)
    assert wd.can_buy_adult(premium=True, adult=True)
    cat = wd.catalog(_uid(), 'anna_01', adult_open=False)
    adult = next(s for s in cat['sections'] if s['key'] == 'adult')
    assert all(i['locked'] for i in adult['items'])


def test_wiring():
    assert "'/webapp/api/wardrobe/buy'" in MAIN and '_deliver_wardrobe_photo' in MAIN
    assert 'spend_peaches(telegram_id, item.price)' in MAIN
    assert 'add_peaches(telegram_id, back)' in MAIN  # failed try-on gives the photo part back
    assert 'photo_overrides' in PHOTO and "'his gift'" in PHOTO
    assert 'wardrobe_service import chat_line' in CHAT
    assert 'id="wdSheet"' in APP and 'openWardrobe' in APP and "open') === 'wardrobe'" in APP
    assert "Command('wardrobe')" in MAIN
