"""V3.153.0: owner ТЗ (Фогель, Модуль 4) — «🎁 Подарки»: четыре позиции, которые
не сгорают вместе с днём.

Что проверяем:
1. четыре позиции и цены из config (импульсный слой рядом с гардеробом), очки
   прогресса ТЗ пересчитаны в нашу шкалу, а не взяты дословно;
2. `current_outfit` — последний подаренный подарок едет в промпт каждой следующей
   фотографии, пока его не заменит другой; у другой девушки его нет;
3. сцена решает, где подарок видно: снаружи дома/в машине/на вечеринке, underneath
   на улице и в голых кадрах, ошейник — поверх всего; полностью голые сцены не
   одеваются обратно;
4. два временных эффекта (вино, БДСМ-сет) — счётчики её живых ответов: тикают
   только на живом диалоге, вино двигает только уровень, но не премиум и не 18+;
5. дорогое подарок (>= GIFT_AUTO_PHOTO_MIN_PEACHES) приходит со своим фото,
   дешёвое — нет: рендер стоит ~250 🍑;
6. витрина: 18+ позиции залочены без Premium, покупка один раз, деньги списывает
   вызывающий код (main.py) с откатом.
"""
import random
from pathlib import Path

from config import (GIFT_AUTO_PHOTO_MIN_PEACHES, GIFT_COLLAR_PEACHES,
                    GIFT_LACE_PEACHES, GIFT_LATEX_PEACHES, GIFT_PASSION_TURNS,
                    GIFT_POINTS_SCALE, GIFT_WINE_MIN_LEVEL, GIFT_WINE_PEACHES,
                    GIFT_WINE_TURNS)
from models.app_models import Base
from services import gift_shop_service as gs
from services.chat_service import EXPLICIT_CHAT_RULE, explicit_chat_line
from services.db import engine

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
APP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
CONF = (ROOT / 'config.py').read_text(encoding='utf-8')


def _uid():
    Base.metadata.create_all(engine)
    return random.randint(3_000_000_000, 3_999_999_999)


# ── 1. каталог ────────────────────────────────────────────────────────────

def test_four_positions_and_their_prices_come_from_config():
    assert [g.id for g in gs.GIFTS] == ['lace', 'latex', 'collar', 'wine']
    assert gs.get('lace').price == GIFT_LACE_PEACHES == 150
    assert gs.get('latex').price == GIFT_LATEX_PEACHES == 250
    assert gs.get('collar').price == GIFT_COLLAR_PEACHES == 400
    assert gs.get('wine').price == GIFT_WINE_PEACHES == 100
    assert gs.get('nope') is None
    # impulse tier: below the wardrobe, whose price carries a render
    from config import CHAT_PHOTO_PEACH_COST
    assert max(g.price for g in gs.GIFTS) == GIFT_COLLAR_PEACHES == 400
    assert gs.get('lace').price < CHAT_PHOTO_PEACH_COST
    # the ТЗ «+20/+35/+60 очков к прогрессу уровня»
    assert [g.points for g in gs.GIFTS] == [20, 35, 60, 0]


def test_tz_points_are_scaled_into_our_five_axes():
    # raw +20 on a 0..100 axis would sell a level outright for 150 🍑
    assert GIFT_POINTS_SCALE == 0.05
    rel, intimacy = gs.points_delta(20)
    assert (rel, intimacy) == (1.0, 0.6)
    assert gs.points_delta(60)[0] == 3.0
    assert gs.points_delta(0) == (0.0, 0.0)
    assert 'GIFT_POINTS_SCALE' in CONF and 'GIFT_LACE_PEACHES' in CONF


def test_wine_is_a_mood_not_an_outfit():
    wine = gs.get('wine')
    assert wine.slot == 'none' and wine.outfit == '' and not wine.adult
    assert gs.get('lace').adult and gs.get('collar').adult


# ── 2. current_outfit ─────────────────────────────────────────────────────

def test_gift_stays_on_until_the_next_one_replaces_it():
    uid = _uid()
    assert gs.worn(uid, 'anna_01') is None and gs.current_outfit(uid, 'anna_01') == ''
    assert gs.grant(uid, 'anna_01', 'lace')
    assert not gs.grant(uid, 'anna_01', 'lace')          # one purchase per girl
    assert gs.current_outfit(uid, 'anna_01') == gs.get('lace').outfit
    assert gs.worn(uid, 'lana_01') is None               # another girl has nothing
    assert gs.grant(uid, 'lana_01', 'lace')
    assert gs.worn(uid, 'lana_01').id == 'lace'
    # the next gift replaces it, the old one stays in her drawer
    assert gs.grant(uid, 'anna_01', 'latex')
    assert gs.current_outfit(uid, 'anna_01') == gs.get('latex').outfit
    assert set(gs.owned_ids(uid, 'anna_01')) == {'lace', 'latex'}
    # wine changes nothing she wears, only how she behaves
    assert gs.grant(uid, 'anna_01', 'wine')
    assert gs.current_outfit(uid, 'anna_01') == gs.get('latex').outfit
    assert set(gs.owned_ids(uid, 'anna_01')) == {'lace', 'latex', 'wine'}


def test_unknown_gift_is_not_granted():
    uid = _uid()
    assert not gs.grant(uid, 'anna_01', 'knife')
    assert gs.owned_ids(uid, 'anna_01') == []


def test_a_bottle_is_the_only_repeat_sale():
    uid = _uid()
    assert gs.repeatable(gs.get('wine'))
    assert not any(gs.repeatable(g) for g in gs.GIFTS if g.id != 'wine')
    assert gs.grant(uid, 'anna_01', 'wine')
    for _ in range(GIFT_WINE_TURNS):
        gs.tick(uid, 'anna_01')
    assert gs.boosts(uid, 'anna_01')['wine'] == 0
    assert gs.grant(uid, 'anna_01', 'wine')                 # the next bottle, same row
    assert gs.boosts(uid, 'anna_01')['wine'] == GIFT_WINE_TURNS
    assert gs.owned_ids(uid, 'anna_01') == ['wine']
    assert gs.grant(uid, 'anna_01', 'lace')
    assert not gs.grant(uid, 'anna_01', 'lace')             # a keepsake is charged once
    cat = gs.catalog(uid, 'anna_01', adult_open=True)
    by_id = {i['id']: i for i in cat['items']}
    assert by_id['wine']['owned'] and by_id['wine']['repeat']
    assert by_id['lace']['owned'] and not by_id['lace']['repeat']


# ── 3. фото ───────────────────────────────────────────────────────────────

def test_scene_decides_where_the_gift_is_visible():
    uid = _uid()
    gs.grant(uid, 'anna_01', 'lace')
    lace = gs.get('lace').outfit
    assert gs.photo_overrides(uid, 'anna_01', 'selfie', 'day_casual') == {'underwear': lace}
    assert gs.photo_overrides(uid, 'anna_01', 'street', 'warm_outdoor') == {'underwear': lace}
    assert gs.photo_overrides(uid, 'anna_01', 'home', 'home') == {'clothing': lace}
    assert gs.photo_overrides(uid, 'anna_01', 'kitchen', 'home') == {'clothing': lace}
    assert gs.photo_overrides(uid, 'anna_01', 'mirror', 'fashion') == {'clothing': lace}
    # a nude frame is not covered back up — the gift says what she took off
    assert gs.photo_overrides(uid, 'anna_01', 'nude', 'adult') == {'underwear': lace}
    assert gs.photo_overrides(uid, 'anna_01', 'shower', 'adult') == {'underwear': lace}
    assert gs.photo_overrides(uid, 'lana_01', 'home', 'home') == {}


def test_collar_goes_over_everything():
    uid = _uid()
    gs.grant(uid, 'anna_01', 'collar')
    o = gs.get('collar').outfit
    assert gs.photo_overrides(uid, 'anna_01', 'nude', 'adult') == {'accessory': o}
    assert gs.photo_overrides(uid, 'anna_01', 'cafe', 'day_casual') == {'accessory': o}
    assert gs.photo_overrides(uid, 'anna_01', 'club', 'evening') == {'accessory': o}


def test_expensive_gift_brings_its_own_photo():
    assert gs.auto_photo(gs.get('collar'))                      # 400 🍑 ≥ 400 🍑
    assert not gs.auto_photo(gs.get('lace')) and not gs.auto_photo(gs.get('latex'))
    assert not gs.auto_photo(gs.get('wine'))                    # nothing to photograph
    assert GIFT_AUTO_PHOTO_MIN_PEACHES == 400
    assert gs.get('collar').tryon == 'lingerie'


# ── 4. поведение ──────────────────────────────────────────────────────────

def test_effect_counters_only_burn_on_live_replies():
    uid = _uid()
    assert gs.boosts(uid, 'anna_01') == {'passion': 0, 'wine': 0}
    gs.grant(uid, 'anna_01', 'wine')
    assert gs.boosts(uid, 'anna_01')['wine'] == GIFT_WINE_TURNS
    for _ in range(GIFT_WINE_TURNS + 3):
        gs.tick(uid, 'anna_01')
    assert gs.boosts(uid, 'anna_01') == {'passion': 0, 'wine': 0}
    gs.tick(uid, 'anna_01')                                     # nothing left to spend
    gs.grant(uid, 'anna_01', 'collar')
    assert gs.boosts(uid, 'anna_01')['passion'] == GIFT_PASSION_TURNS == 10
    gs.tick(uid, 'anna_01')
    assert gs.boosts(uid, 'anna_01')['passion'] == GIFT_PASSION_TURNS - 1


def test_wine_opens_the_level_gate_but_never_the_paywall():
    assert gs.wine_opens_level(GIFT_WINE_MIN_LEVEL) and gs.wine_opens_level(9)
    assert not gs.wine_opens_level(GIFT_WINE_MIN_LEVEL - 1) and not gs.wine_opens_level(0)
    # no 18+ confirmation → no explicit rule, wine or not
    assert explicit_chat_line('close', adult_confirmed=False, premium=True, wine=True) == ''
    # no Premium → the owner's paywall still holds
    assert explicit_chat_line('close', adult_confirmed=True, premium=False, wine=True) == ''
    assert explicit_chat_line('close', adult_confirmed=True, premium=True) == ''
    assert explicit_chat_line('close', adult_confirmed=True, premium=True, wine=True) == EXPLICIT_CHAT_RULE


def test_prompt_lines_say_what_he_bought_and_never_ask_for_more():
    uid = _uid()
    assert gs.chat_line(uid, 'anna_01') == ''
    gs.grant(uid, 'anna_01', 'lace')
    gs.grant(uid, 'anna_01', 'latex')
    line = gs.chat_line(uid, 'anna_01')
    assert 'сейчас на тебе латексное мини-платье' in line
    assert 'красное кружевное бельё' in line and 'ЕГО ПОДАРКИ' in line
    assert 'Никогда не проси новых подарков' in line
    assert 'wine' not in line.lower()
    assert 'МАКСИМУМ СТРАСТИ' in gs.passion_line()
    assert 'ВЗБЕДРИВШЕЕ ВИНЦО' in gs.wine_line(GIFT_WINE_MIN_LEVEL)
    assert 'его 18+' in gs.wine_line(GIFT_WINE_MIN_LEVEL)
    assert 'границу приличия пока держишь' in gs.wine_line(1)   # below the gate: mood only


def test_gift_scene_and_action_are_his_words_not_a_shop_pitch():
    scene = gs.gift_scene(gs.get('lace'), 'Анна')
    assert 'СЦЕНА ПОДАРКА' in scene and 'Анна' in scene
    assert 'попроси оценить' in scene and 'без просьб о новых подарках' in scene
    assert 'дарю тебе подарок' in gs.gift_action(gs.get('wine'), 'ru')
    assert 'hands you a gift' in gs.gift_action(gs.get('wine'), 'en')
    for g in gs.GIFTS:
        assert 'не проси' not in gs.gift_scene(g)


# ── 5. витрина ────────────────────────────────────────────────────────────

def test_catalog_locks_adult_items_and_shows_the_state():
    uid = _uid()
    cat = gs.catalog(uid, 'anna_01', 'ru', adult_open=False)
    by_id = {i['id']: i for i in cat['items']}
    assert by_id['lace']['locked'] and by_id['collar']['locked']
    assert not by_id['latex']['locked'] and not by_id['wine']['locked']
    assert cat['worn'] == '' and cat['wine'] == 0
    assert by_id['lace']['art'] == '/webapp/art/wd_lace.jpg'
    assert by_id['collar']['art'] == ''            # no invented asset: the emoji shows
    gs.grant(uid, 'anna_01', 'wine')
    cat = gs.catalog(uid, 'anna_01', 'en', adult_open=True)
    by_id = {i['id']: i for i in cat['items']}
    assert not by_id['lace']['locked'] and by_id['lace']['title'] == 'Red lace lingerie'
    assert by_id['wine']['owned'] and cat['wine'] == GIFT_WINE_TURNS


# ── 6. проводка ───────────────────────────────────────────────────────────

def test_app_endpoints_charge_then_grant_with_a_refund():
    assert "'/webapp/api/gifts'" in MAIN and "'/webapp/api/gifts/buy'" in MAIN
    fn = MAIN[MAIN.index('async def _webapp_api_gifts_buy_impl'):MAIN.index('async def _deliver_gift_photo')]
    assert 'spend_peaches(telegram_id, gift.price)' in fn
    assert 'add_peaches(telegram_id, gift.price)' in fn        # failed write gives it back
    assert "'insufficient_peaches'" in fn and "'owned'" in fn
    assert 'not _wardrobe_adult_open(telegram_id)' in fn       # 18+ gifts: Premium + 18+
    assert 'gift_shop_service.repeatable(gift)' in fn          # a bottle may be bought again
    assert "track_event(uid_, 'gift_buy'" in fn
    assert 'gift_shop_service.points_delta(gift.points)' in fn
    assert '_feature_scene_turn' in fn and 'auto_photo(gift)' in fn
    assert "Command('gifts')" in MAIN and "webapp?open=gifts" in MAIN


def test_outfit_reaches_the_photo_prompt_after_the_wardrobe():
    block = PHOTO[PHOTO.index('def _resolve_request'):PHOTO.index('pack_outfits = tuple(')]
    assert 'gift_photo_overrides' in block
    assert "gf.get('clothing') and not request.clothing" in block  # wardrobe keeps its slot
    assert "if gf.get('underwear') and not wd.get('underwear'):" in block
    assert 'SCENE_GROUP.get(request.scene' in block
    assert 'request.pack_outfits' in block                        # progression packs win


def test_a_gift_she_wears_shows_up_in_no_shared_photo():
    # his lace at home renders fresh; the same gift hidden under her street clothes does not
    block = PHOTO[PHOTO.index('home_lingerie_mode = ('):]
    block = block[:block.index('# Community pool first')]
    assert 'gift_shop_service.photo_overrides' in block
    assert "_gs.get('clothing') or _gs.get('accessory')" in block


def test_dialog_reads_boosts_once_and_spends_them_only_on_live_replies():
    assert 'gift_shop_service.boosts(user_id, character_id)' in CHAT
    assert "persona_style = 'passionate'" in CHAT
    assert '_gshop.chat_line(user_id, character_id)' in CHAT
    assert 'wine=gift_wine_open' in CHAT
    tick = CHAT[CHAT.index('def reply('):]
    assert 'if not scene and (r.text or \'\').strip():' in tick    # pushes never burn it
    assert 'gift_shop_service.tick(user_id, character_id)' in tick


def test_mini_app_gift_sheet():
    assert 'id="gsSheet"' in APP and 'function openGifts' in APP and 'function renderGifts' in APP
    assert "'/webapp/api/gifts?character_id='" in APP and "'/webapp/api/gifts/buy?init_data='" in APP
    assert "sp.get('open') === 'gifts'" in APP and 'if (gifts) openGifts();' in APP
    assert 'id="featGifts"' in APP and 'L.gs_cap' in APP
    assert APP.count('it.owned && !it.repeat') == 2            # priced and buyable again
    buy = APP[APP.index('async function giftBuy'):APP.index("if (document.getElementById('gsClose'))")]
    assert "j.error === 'premium_required'" in buy and "j.error === 'owned'" in buy
    assert 'quickBuy' in buy and 'chatBubble' in buy and 'waitForDatePhoto' in buy
