"""Static regression tests for v3.17.0: apartment rooms, gifts and dates.

Apartment/dates are gated by relationship level, gifts and dates are paid
with Telegram Stars through the shared pre_checkout/successful_payment flow,
and a paid date ends with a fresh photo set from the date scene.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_apartment_catalog_level_gating():
    from services.apartment_service import ROOMS, get_available_rooms, get_locked_rooms, get_room
    assert {r.id for r in ROOMS} == {'living', 'kitchen', 'bedroom', 'bathroom', 'candles'}
    assert all(r.min_level >= 1 for r in ROOMS)
    # Level 1 sees only the living room; everything unlocks by level 8
    # (V3.21.0 moved the ceiling from 6 to the premium plateau).
    assert [r.id for r in get_available_rooms(1)] == ['living']
    assert len(get_available_rooms(8)) == len(ROOMS)
    assert not get_locked_rooms(8)
    assert get_room('bedroom').min_level == 3
    assert get_room('no_such_room') is None


def test_apartment_actions_resolve_and_gate():
    from services.apartment_service import room_action_reply
    reply = room_action_reply('living', 'movie')
    assert reply and reply[0]
    # Actions not declared for the room must not resolve.
    assert room_action_reply('living', 'shower') is None
    assert room_action_reply('no_room', 'talk') is None


def test_gifts_catalog_costs():
    from services.gifts_service import GIFTS, get_all, get
    assert len(GIFTS) >= 5
    assert all(g.cost >= 1 and g.affection > 0 and g.reaction for g in GIFTS)
    assert get_all() == list(GIFTS)
    assert get('flowers').cost == GIFTS[1].cost
    assert get('no_such_gift') is None


def test_dates_catalog_level_gating_and_scenes():
    from services.dates_service import DATES, get_available, get_locked, get
    assert {d.id for d in get_available(8)} == {d.id for d in DATES}
    assert not get_locked(8)
    assert get_available(1) and all(d.min_level == 1 for d in get_available(1))
    # Every reward scene must be a known photo scene so the reward set can be generated.
    from services.photo_service import SCENES
    for d in DATES:
        assert d.scene in SCENES, f'date {d.id} reward scene {d.scene} unknown'
        assert d.cost >= 1 and d.affection > 0
    assert get('no_such_date') is None


def test_main_keyboard_has_new_buttons():
    # V3.22.0: keyboard labels moved to services/ui_lang.py as (ru, en) pairs;
    # handlers match both variants via F.text.in_(kb_pair(key)).
    from services.ui_lang import KB_LABELS
    assert KB_LABELS['apartment'] == ('🏠 Квартира', '🏠 Apartment')
    assert KB_LABELS['date'] == ('💕 Свидание', '💕 Date')
    assert KB_LABELS['gift'] == ('🎁 Подарить', '🎁 Gift')
    for key in ('apartment', 'date', 'gift'):
        assert f"F.text.in_(kb_pair('{key}'))" in MAIN


def test_room_enter_looks_up_room_by_id():
    # The room must be resolved by id, never by indexing the first available room.
    block = MAIN[MAIN.index("async def room_enter("):MAIN.index("async def room_locked(")]
    assert 'apartment_service.get_room(' in block
    assert 'get_available_rooms(6)[0]' not in block
    # Level gate: a locked room must be rejected before rendering actions.
    assert 'room.min_level > level' in block
    assert "callback_data=f'apt_action:{room.id}:{action_id}'" in block


def test_apartment_action_applies_relationship_delta():
    block = MAIN[MAIN.index("async def room_action("):MAIN.index("async def gifts_cmd(")]
    assert 'apartment_service.room_action_reply(room_id, action_id)' in block
    assert 'await record_user_message(' in block
    assert "character_id=character_id" in block


def test_gift_and_date_purchase_via_stars_invoice():
    gift_block = MAIN[MAIN.index("async def gift_buy("):MAIN.index("async def dates_cmd(")]
    assert "send_stars_invoice(" in gift_block and "f'gift:{gift.id}'" in gift_block
    date_block = MAIN[MAIN.index("async def date_start("):MAIN.index("async def date_locked(")]
    assert "send_stars_invoice(" in date_block and "f'date:{date.id}'" in date_block
    assert 'date.min_level > level' in date_block


def test_pre_checkout_validates_gift_and_date():
    block = MAIN[MAIN.index('async def pre_checkout('):MAIN.index('async def successful_payment(')]
    assert "payload.startswith('gift:')" in block
    assert 'amount == gifts_service.effective_cost(gift)' in block
    assert "payload.startswith('date:')" in block
    assert 'amount == date.cost' in block
    # Dates must also be re-checked against the user's current level at checkout.
    assert 'date.min_level <= get_relationship_level(query.from_user.id, get_user_character(query.from_user.id))' in block


def test_successful_payment_handles_gift_and_date():
    block = MAIN[MAIN.index('async def successful_payment('):MAIN.index('# === КВАРТИРА')]
    gift_part = block[block.index("payload.startswith('gift:'):"):]
    assert "record_payment(message.from_user.id, 'gift'" in gift_part
    assert 'await record_user_message(' in gift_part
    date_part = block[block.index("payload.startswith('date:'):"):]
    assert "record_payment(message.from_user.id, 'date'" in date_part
    # Paid date goes through the shared reward path.
    assert 'await _deliver_date_reward(message.chat.id, message.from_user.id' in date_part
    # The shared reward path ends with a fresh photo set from the date scene.
    helper = MAIN[MAIN.index('async def _deliver_date_reward('):]
    helper = helper[:helper.index('@dp.message')]
    assert "PhotoRequest(scene=date.scene, mood='romantic')" in helper
    assert '_start_photo_background(chat_id, telegram_id' in helper


def test_new_handlers_registered_before_text_catch_all():
    # Dual-language handlers must be registered before the generic F.text handler.
    for key in ('apartment', 'gift', 'date'):
        assert MAIN.index(f"kb_pair('{key}')") < MAIN.index('@dp.message(F.text)\n')
