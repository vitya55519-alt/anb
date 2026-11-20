import inspect

from services import life_event_service as le
from services import private_photo_service as pps
from services import spend_service


def test_her_day_pool_is_ten_short_texts_5_and_5():
    assert len(le.HER_DAY_TEXTS_18) == 5 and len(le.HER_DAY_TEXTS_NORMAL) == 5
    assert all(len(t) <= 160 for t in le.HER_DAY_TEXTS_18 + le.HER_DAY_TEXTS_NORMAL)
    assert le.her_day_pool(True) is le.HER_DAY_TEXTS_18
    assert le.her_day_pool(False) is le.HER_DAY_TEXTS_NORMAL


def test_her_day_has_two_quick_buttons_with_tap_text():
    for spicy in (True, False):
        opts = le.her_day_options(spicy, 'rita_01')
        assert len(opts) == 2
        for _lbl, cb in opts:
            assert cb.startswith('life_reply:rita_01:')
            assert le.tap_reply_text(cb.split(':')[2]) != 'расскажи подробнее'


def test_source_lands_in_ledger_scene_and_log():
    spend_service.set_spend_source('greeting')
    assert spend_service.current_spend_source() == 'greeting'
    spend_service.set_spend_source('nonsense')
    assert spend_service.current_spend_source() == 'other'
    src = inspect.getsource(pps._spicyapi_render_once)
    assert 'source={spend_service.current_spend_source()}' in src
    assert 'billed=task_accepted' in src
    assert 'chat_free' in spend_service.FREE_SPEND_SOURCES


def test_idempotency_key_is_stable_until_provider_answers():
    block = {'prompt': 'x', 'image_urls': ['a']}
    k1 = pps._idempotency_key('m', block)
    assert pps._idempotency_key('m', block) == k1          # retry after a timeout
    pps._spicy_pending_keys.clear()                         # provider answered
    assert pps._idempotency_key('m', block) != k1
    assert pps._idempotency_key('m', {**block, 'enable_thinking': True}) != pps._idempotency_key('m', block)
