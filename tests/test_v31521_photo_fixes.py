"""V3.152.1: owner ТЗ (Фогель) — duo renders two women, the guest pool is
official-only, hot frames look like her own phone photos, lingerie never lands
in a bar, and the row under her picture has no «Скачать».

Pinned here: the three prompt locks and where they sit (the SpicyAPI cap eats
the tail, so a lock at the end is a lock the provider never reads), the
official-only guest gate on read, write and auto-pick, and the app markup.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
CGS = (ROOT / 'services' / 'chat_guest_service.py').read_text(encoding='utf-8')
FUNNEL = (ROOT / 'services' / 'invite_funnel.py').read_text(encoding='utf-8')
LIVE = (ROOT / 'services' / 'live_situation_service.py').read_text(encoding='utf-8')

import services.photo_service as ps
import services.private_photo_service as pps
from services.chat_guest_service import can_invite, is_official_guest


def _bubble(html: str) -> str:
    # her photo row only — his own picture keeps its save button on purpose
    start = html.index("else if (cls === 'bot') {")
    return html[start:html.index('else body = `', start)]


def _body(source: str, marker: str) -> str:
    return source[source.index(marker):source.index(marker) + 3500]


# ── Задача 1: UI чистка ────────────────────────────────────────────────────

def test_no_download_button_under_her_photo():
    bubble = _bubble(INDEX)
    assert 'data-pact="undress"' in bubble and 'data-pact="animate"' in bubble
    assert 'pa_save' not in bubble and 'data-dl' not in bubble


def test_the_row_is_two_strict_rows():
    # «Раздеть» on the whole first row, «Оживить» and «Вдвоём» share the second.
    hot = INDEX[INDEX.index('.msg .phact .pa.hot'):]
    assert 'order: -1' not in hot.split('.msg .phact .pa:disabled')[0]
    assert "grid-template-columns: 1fr 1fr" in INDEX
    assert "grid-column: 1 / -1" in INDEX
    assert 'async function openGuestPicker' in INDEX
    # no second girl in the chat — «Оживить» closes the row instead of leaving
    # half of it empty
    assert ".msg .phact .pa.wide { grid-column: 1 / -1; }" in INDEX
    assert '''<button class="pa' + (CHAT && CHAT.guest ? '' : ' wide') + '" data-pact="animate"''' in INDEX


def test_the_paid_stars_download_is_not_the_chat_row():
    # V3.152.1 removes the free chat button only: the album download for 30⭐
    # and the lightbox save stay, they are a paid product, not decoration.
    assert 'gallery:dl:' in MAIN and 'id="lbDownload"' in INDEX


# ── Задача 2: только официальные героини ───────────────────────────────────

def test_a_constructor_build_is_never_a_guest():
    assert is_official_guest('custom_777_deadbeef') is False
    assert can_invite(1, 'anna_01', 'custom_777_deadbeef') is False
    assert is_official_guest('') is False


def test_the_official_gate_reads_the_storefront_card(monkeypatch):
    import services.character_card_service as ccs

    class Card:
        status = 'active'
        is_visible = True

    monkeypatch.setattr(ccs, 'get_card', lambda cid: Card())
    assert is_official_guest('kamila_01') is True
    Card.is_visible = False
    assert is_official_guest('kamila_01') is False


def test_read_write_and_autopick_all_use_the_official_pool():
    assert 'if guest_id and not is_official_guest(guest_id):' in CGS          # set_guest
    get = _body(CGS, 'def get_guest(')
    assert 'not is_official_guest(guest_id)' in get                            # stale custom row
    assert 'return is_official_guest(guest_id)' in _body(CGS, 'def can_invite(')
    assert 'is_official_guest(card.character_id)' in _body(FUNNEL, 'def pick_guest(')
    assert "c.id !== characterId && c.status === 'active' && !c.custom" in INDEX


# ── Задача 3: «Вдвоём» рисует двух девушек ─────────────────────────────────

def test_the_duo_head_declares_both_women_first():
    req = ps.PhotoRequest(scene='selfie', location='a sunny cafe terrace', with_guest='kamila_01')
    prompt = ps._build_prompt(req, 0, seedream=True, relationship_level=2, character_id='anna_01')
    assert prompt.startswith('TWO WOMEN IN FRAME: two girls together, interacting, two women in frame.')
    assert 'Girl 1: ' in prompt and 'Girl 2: Камила' in prompt
    assert 'jet-black' in prompt            # the guest's own look, not a guess
    assert prompt.index('Girl 2:') < prompt.index('SCENE:')


def test_a_solo_photo_has_no_duo_head():
    prompt = ps._build_prompt(ps.PhotoRequest(scene='selfie'), 0, seedream=True,
                              relationship_level=2, character_id='anna_01')
    assert 'TWO WOMEN IN FRAME' not in prompt


def test_the_guest_block_left_the_trim_zone():
    # V3.61.2 put it as the last line — exactly where _fit_spicy_prompt cuts.
    src = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
    leg = _body(src, 'async def _run_spicy_set(')
    assert 'duo_block=guest_block' in leg
    assert "prompt += '\\n' + guest_block" not in leg
    assert 'TWO WOMEN IN FRAME:' in pps._SPICY_TIERS[-1]


def test_the_locks_survive_the_spicyapi_cap():
    req = ps.PhotoRequest(scene='selfie', location='a crowded office floor', with_guest='kamila_01')
    built = ps._build_prompt(req, 0, seedream=True, relationship_level=6, character_id='anna_01',
                             duo_block=ps._guest_photo_block('anna_01', 'kamila_01', 'an office'))
    fitted = pps._fit_spicy_prompt(built + '\n' + ('filler sentence about the scene. ' * 400))
    assert len(fitted) <= pps.SPICYAPI_PROMPT_MAX
    for head in ('TWO WOMEN IN FRAME:', 'AMATEUR HOT FRAME:', 'PRIVATE PLACE OVERRIDE:'):
        assert head in fitted


# ── Задача 4: эстетика «живых нюдсов» ──────────────────────────────────────

def test_hot_frames_get_the_amateur_lock():
    lingerie = ps._build_prompt(ps.PhotoRequest(scene='lingerie'), 0, seedream=True,
                                 relationship_level=5, character_id='anna_01')
    assert 'AMATEUR HOT FRAME:' in lingerie
    assert 'amateur mirror or handheld selfie' in lingerie.lower()
    assert 'professional photoshoot' in lingerie and 'studio lighting' in lingerie
    dressed = ps._build_prompt(ps.PhotoRequest(scene='cafe'), 0, seedream=True,
                               relationship_level=2, character_id='anna_01')
    assert 'AMATEUR HOT FRAME' not in dressed


def test_the_general_audience_route_never_hears_about_lingerie():
    openai_leg = ps._build_prompt(ps.PhotoRequest(scene='nude'), 0, seedream=False,
                                  relationship_level=6, character_id='anna_01')
    assert 'AMATEUR HOT FRAME' not in openai_leg and 'PRIVATE PLACE OVERRIDE' not in openai_leg


def test_private_menu_hot_categories_are_amateur_too():
    hot = pps.build_private_photo_prompt(
        pps.PrivatePhotoRequest(category='lingerie', type_id='bra', location_id='bedroom', mood_id='bold'),
        'an adult woman')
    assert 'AMATEUR HOT FRAME:' in hot
    # «Фотостудия» is his own choice — there the studio look stays.
    studio = pps.build_private_photo_prompt(
        pps.PrivatePhotoRequest(category='lingerie', type_id='bra', location_id='studio', mood_id='bold'),
        'an adult woman')
    assert 'AMATEUR HOT FRAME:' not in studio


def test_the_paid_undress_edit_is_a_phone_photo_too():
    prompt = _undress_prompt()
    assert 'AMATEUR HOT FRAME:' in prompt and 'PLACE: keep the room of image 1' in prompt


def _undress_prompt():
    import main
    text, _secret = main._undress_prompt(1, 'anna_01')
    return text


# ── Задача 5: откровенность живёт только за закрытой дверью ─────────────────

def test_lingerie_is_moved_out_of_a_public_venue():
    req = ps.PhotoRequest(scene='selfie', location='her office desk at the end of the workday')
    prompt = ps._build_prompt(req, 0, seedream=True, relationship_level=5, character_id='anna_01')
    assert prompt.startswith('PRIVATE PLACE OVERRIDE:')
    assert 'PRIVATE PLACE OVERRIDE' in prompt


def test_clothed_photos_keep_the_venue():
    kept = ps._build_prompt(ps.PhotoRequest(scene='bar', location='a crowded sports bar'), 0,
                            seedream=True, relationship_level=2, character_id='anna_01')
    assert 'PRIVATE PLACE OVERRIDE' not in kept
    assert ps.enforce_private_location('a busy cafe with customers around, she wears a linen dress') \
        .startswith('a busy cafe')


def test_his_own_wish_for_exhibition_wins():
    prompt = 'she is in lace lingerie on the balcony above the street'
    # no wish from him → the venue moves behind a closed door
    moved = ps.enforce_private_location(prompt)
    assert moved != prompt and moved.startswith('PRIVATE PLACE OVERRIDE:')
    # he asked for it in words → her balcony stays
    assert ps.enforce_private_location(prompt, 'покажи фотку на балконе, чтобы весь двор видел') == prompt
    assert ps.enforce_private_location(prompt, 'сними себя на улице, чтобы люди видели') == prompt
    assert ps.enforce_private_location(prompt, 'show me in public tonight') == prompt


def test_his_words_are_read_in_the_imperative_too():
    # «покажи/покажешь» live on the корень покаж-, not показ- — a regex that
    # only knows «показ» lets his own wish through and moves her indoors.
    for wish in ('покажи фотку на балконе', 'покажешь себя на улице?', 'сними себя на людях'):
        assert ps.wants_public_exposure(wish), wish
    for plain in ('покажи новое платье', 'пришли фото из бара в платье'):
        assert not ps.wants_public_exposure(plain), plain


def test_the_ru_venue_leak_is_detected():
    assert ps.PUBLIC_VENUE.search('location=офис, activity=working')
    assert ps.PUBLIC_VENUE.search('в душной маршрутке в пробке')
    # words that only look like a venue must not fire («бархат», «клубника»,
    # «паркет», «стиральная машинка», «кафель»)
    for harmless in ('бархатный диван', 'клубничный цвет', 'паркетный пол', 'стиральная машинка', 'кафель'):
        assert not ps.PUBLIC_VENUE.search(harmless), harmless


def test_live_situations_lock_the_private_place_instead_of_fighting_it():
    assert 'ты НЕ МОЖЕШЬ находиться в общественном месте' in LIVE
    assert 'IMAGE_PRIVATE_LOCATION_LOCK' in LIVE
    unlock = _body(LIVE, 'async def unlock_photo(')
    assert 'enforce_private_location(prompt)' in unlock
    assert 'IMAGE_PRIVATE_LOCATION_LOCK' in unlock
    assert 'IMAGE_LOCATION_LOCK}' in unlock


def test_the_private_pipeline_routes_the_menu_categories():
    assert "intimate=request.category in HOT_PRIVATE_CATEGORIES" in (
        ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')
    assert {'lingerie', 'fully_nude', 'nude_art', 'suggestive'} == set(pps.HOT_PRIVATE_CATEGORIES)


def test_custom_guest_row_is_read_as_no_guest(monkeypatch):
    # an old ChatGuest row holding a constructor build must not survive into a duo prompt
    import services.chat_guest_service as cgs
    monkeypatch.setattr(cgs, 'is_official_guest', lambda gid: False)
    assert cgs.get_guest(1, 'anna_01') in (None, '')
