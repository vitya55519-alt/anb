"""V3.167.27 (владелец, 20 ноя): «✨ Фантазия» — отдельная функция, его слова
рисует та женщина, с которой он в чате.

Его рельсы по ТЗ:

* панель над «✨ Возможности», по умолчанию открыта, сворачивается (и сама
  полоса «Возможности» тоже — «сделай чтобы кнопка возможности тоже
  сварачивалась»);
* 1 кадр бесплатно в сутки — ТОЛЬКО для Premium (V3.168.1), дальше и без
  Premium — та же цена голого кадра (EXPLICIT_PHOTO_PEACH_COST);
* деньги списываются только после доставленного кадра: сбой и отказ генератора
  не стоят ни персика и не сжигают бесплатный слот;
* фильтров с нашей стороны нет — только несъёмные жёсткие пределы генератора;
* режим романтики — цензура, 18+ — без цензуры;
* «это если что новая отдельная функция»: старый платный путь фетишей
  (звёзды, V3.23.0) не тронут.
"""
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services import fetish_mode, wish_service

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
PPS = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')
PHS = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')

MSK = timezone(timedelta(hours=3))


import pytest


@pytest.fixture(autouse=True)
def _premium_account(monkeypatch):
    # V3.168.1: the free daily frame is Premium-only; these tests exercise that slot.
    import services.access_service as acc
    monkeypatch.setattr(acc, 'is_premium', lambda tid: True)


def test_a_non_premium_account_has_no_free_frame_and_pays_peaches(monkeypatch):
    import sys
    import services.access_service as acc
    monkeypatch.setattr(acc, 'is_premium', lambda tid: False)
    payments = types.ModuleType('services.payments')
    spent: list = []
    payments.spend_peaches = lambda tid, amount, paid_only=False: (spent.append(amount) or True)
    saved = sys.modules.get('services.payments')
    sys.modules['services.payments'] = payments
    try:
        tid = _tid()
        assert wish_service.free_available(tid) is False
        assert wish_service.settle(tid) == 'paid'
        assert spent == [wish_service.cost()]
    finally:
        if saved is not None:
            sys.modules['services.payments'] = saved
        else:
            del sys.modules['services.payments']


def _tid() -> int:
    return int(f'95{datetime.now(timezone.utc).strftime("%H%M%S%f")}')


def _yesterday() -> str:
    return (datetime.now(MSK) - timedelta(days=1)).date().isoformat()


# ── его слова ──────────────────────────────────────────────────────────────

def test_three_hundred_letters_and_only_the_hard_limits():
    assert wish_service.WISH_MAX == 300
    long_wish = 'шёлк ' * 100
    cut = wish_service.clean_wish(long_wish)
    assert cut and len(cut) <= 300
    # жёсткие пределы генератора — те же, что в фетишах (несъёмные, владелец не снимал)
    assert wish_service.clean_wish('школьница в форме') is None
    assert wish_service.clean_wish('   ') is None
    # а всё остальное проходит: фильтр на нашей стороне только один — _BLOCKED
    assert wish_service.clean_wish('кружево на кухне, утренний свет')


def test_the_old_fetish_path_keeps_its_own_80_letters():
    # новая функция не должна была тронуть старый лимит фетишей
    assert fetish_mode.CUSTOM_MAX == 80
    assert fetish_mode.clean_custom('a' * 200) is not None
    assert len(fetish_mode.clean_custom('a' * 200)) <= 80


# ── экономика: 1 бесплатный кадр в сутки на аккаунт (живая тестовая БД) ────

def test_the_free_slot_is_one_per_moscow_day():
    from config import EXPLICIT_PHOTO_PEACH_COST
    assert wish_service.cost() == EXPLICIT_PHOTO_PEACH_COST == 250

    tid = _tid()
    assert wish_service.free_available(tid) is True
    wish_service._day[tid] = datetime.now(MSK).date().isoformat()
    assert wish_service.free_available(tid) is False
    wish_service._day[tid] = _yesterday()
    assert wish_service.free_available(tid) is True


def test_the_first_frame_of_the_day_is_free_the_rest_cost_the_explicit_price():
    import sys
    payments = types.ModuleType('services.payments')
    spent: list = []
    payments.spend_peaches = lambda tid, amount, paid_only=False: (
        spent.append((tid, amount, paid_only)) or True)
    saved = sys.modules.get('services.payments')
    sys.modules['services.payments'] = payments
    tid = _tid()
    try:
        assert wish_service.settle(tid) == 'free'
        assert spent == []                          # бесплатный кадр — ни одного списания
        assert wish_service.settle(tid) == 'paid'   # второй кадр того же дня
        assert spent[0][1] == wish_service.cost()
        assert spent[0][2] is True                  # только купленные персики, не бонусные
    finally:
        if saved is not None:
            sys.modules['services.payments'] = saved


def test_a_refused_charge_is_reported_and_never_burns_the_free_slot():
    import sys
    payments = types.ModuleType('services.payments')
    payments.spend_peaches = lambda *a, **k: False  # персиков не хватило
    saved = sys.modules.get('services.payments')
    sys.modules['services.payments'] = payments
    tid = _tid()
    try:
        assert wish_service.settle(tid) == 'free'   # первый кадр дня — бесплатно
        assert wish_service.settle(tid) == 'none'   # второй: слот спалён, платить нечем
        # сбой кассы не должен задним числом съесть ещё один бесплатный слот
        assert wish_service.free_available(tid) is False
    finally:
        if saved is not None:
            sys.modules['services.payments'] = saved
        else:
            del sys.modules['services.payments']


def test_a_dead_store_never_burns_money_silently():
    import sys
    payments = types.ModuleType('services.payments')
    spent: list = []
    payments.spend_peaches = lambda *a, **k: spent.append(a) or False

    class Boom:
        def get(self, tid, default=None):
            raise RuntimeError('db down')

        def __setitem__(self, tid, value):
            raise RuntimeError('db down')

    original = wish_service._day
    saved = sys.modules.get('services.payments')
    wish_service._day = Boom()
    sys.modules['services.payments'] = payments
    try:
        # слот не читается → бесплатным кадр не объявляем; списать не смогли → 'none'
        assert wish_service.free_available(_tid()) is False
        assert wish_service.settle(_tid()) == 'none'
    finally:
        wish_service._day = original
        if saved is not None:
            sys.modules['services.payments'] = saved
        else:
            del sys.modules['services.payments']


# ── маршрут: своя касса, чужие счётчики не трогает ────────────────────────

def _block(start: str, end: str, text: str = MAIN) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_the_wish_route_is_a_separate_door():
    assert "app.router.add_post('/webapp/api/chat/wish', _webapp_api_chat_wish)" in MAIN
    handler = _block('async def _webapp_api_chat_wish(', 'async def _webapp_media(')
    # авторизация те же, что у чата
    assert 'webapp_service.validate_init_data' in handler
    # жёсткие пределы: не прошёл очистку — 400 wish_refused, рисовать не начинаем
    assert 'wish_service.clean_wish' in handler
    assert "'error': 'wish_refused'" in handler
    # 18+ рисует без цензуры, романтика — обычным конвейером
    assert "is_adult_confirmed" in handler
    assert "_webapp_media_hot(telegram_id, character_id, 'fetish:custom'" in handler
    assert "theme_text=text, wish=True" in handler
    assert 'PhotoRequest(scene=' in handler
    # оплата — только после доставленного кадра
    assert handler.index("save_chat_media") < handler.index('wish_service.settle')
    assert "else wish_service.settle(telegram_id)" in handler
    # нехватка персиков — 402 до генерации (дешевле для нас, честнее для него)
    assert '402' in handler and "'credits'" in handler


def test_the_wish_frame_never_touches_the_other_meters():
    hot = _block('async def _webapp_media_hot(', 'async def _webapp_media_hot_circle(')
    assert 'wish: bool = False' in hot
    # бесплатный слот фантазии не берёт ни лимит сообщений, ни бесплатный кадр Premium/пасса
    assert '    free_used = (True if wish else' in hot
    assert "consume_free_private_photo(telegram_id, 'cosplay') if cosplay" in hot
    # его слова не подменяются чужим кадром из копилки
    assert 'None if (series or wish or telegram_id in ADMIN_TELEGRAM_IDS) else pool_get' in hot
    # 300 букв доходят до генератора целиком, а не режутся до 80
    assert 'max_len=fetish_mode.WISH_MAX' in hot


def test_the_message_wall_is_not_spent_by_a_frame():
    handler = _block('async def _webapp_api_chat_wish(', 'async def _webapp_media(')
    assert 'note_message' not in handler


# ── анатомия (его замечание: «на груди нет сосков») ────────────────────────

def test_bare_frames_say_the_anatomy_plainly():
    assert 'visible natural nipples and areolae' in PPS
    assert 'never a smooth featureless chest' in PPS
    assert 'visible natural nipples' in PHS
    assert 'never a smooth featureless chest' in PHS


# ── панель в Mini App ──────────────────────────────────────────────────────

def test_the_panel_sits_above_the_features_strip_and_folds():
    assert SPA.index('id="wishPanel"') < SPA.index('id="featMenuBtn"')
    assert 'maxlength="300"' in SPA
    assert 'class="wishpanel' in SPA or 'class="wishpanel"' in SPA
    assert '.wishpanel.folded .wp-body { display: none; }' in SPA
    assert SPA.count("<span class=\"fm-arrow\">▾</span>") == 1
    assert '.chat-input .featmenu.folded' in SPA
    # стартовое состояние помнится устройством, полоса больше не открывается стрелкой
    assert "setFold(wishPanel, 'wish_fold'" in SPA
    assert "setFold(featMenuBtnEl, 'feat_fold'" in SPA
    # свёрнутая при прошлом визите панель встречает пояснением сразу, а не после тапа
    assert "classList.contains('folded') ? L.wish_fold : ''" in SPA
    assert "document.getElementById('featMenuBtn').addEventListener('click', openCapSheet);" not in SPA


def test_the_panel_talks_to_its_own_door():
    fn = _block('async function wishSend() {', '// V3.167.27: both strips fold', SPA)
    assert "'/webapp/api/chat/wish?init_data='" in fn
    assert 'character_id: chatId' in fn
    assert 'if (!sameChat(chatId)) return;' in fn
    assert "r.status === 402" in fn and "quickBuy('wish', wishSend)" in fn
    assert 'L.wish_refused' in fn
    # полоса ввода кадра не занята, пока он печатает — свой busy-флаг тот же
    assert 'if (mediaBusy) { toast(L.media_busy); return; }' in fn


def test_the_strip_fold_is_reachable_in_both_states():
    # свернуть полосу должно быть можно и в раскрытом виде: стрелка видна всегда,
    # в свёрнутом — доворачивается.
    assert '.featmenu .fm-arrow { position: absolute' in SPA
    assert '.featmenu .fm-arrow { display: none' not in SPA
    assert '.featmenu.folded .fm-arrow { transform: translateY(-50%) rotate(-90deg); }' in SPA


def test_the_words_live_in_both_language_tables():
    en = _block('const L_EN = {', 'const L_RU = {', SPA)
    ru = _block('const L_RU = {', 'const L = LANG', SPA)
    for table, keys in ((en, ('wish_title', 'wish_ph', 'wish_go', 'wish_fold', 'wish_yours', 'wish_refused')),
                        (ru, ('wish_title', 'wish_ph', 'wish_go', 'wish_fold', 'wish_yours', 'wish_refused'))):
        for key in keys:
            assert f'{key}:' in table, key
    assert "wish_refused: 'Такой кадр генератор не рисует — выбери другой сюжет'" in ru
