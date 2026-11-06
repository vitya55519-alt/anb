"""V3.114.0: «👗 Гардероб» — he buys her clothes and things for her room with peaches.

Owner (after Replika): «ему одежда для неё, ей настроение». Every item belongs to
one girl and stays hers forever. A purchase:
  * plays her live reaction in the chat (normal dialog pipeline, a scene note),
  * renders one try-on photo of her in it (the price includes that render,
    which is why the cheapest item is 300 🍑 while a chat photo is 200 🍑),
  * puts the garment on her for the rest of the day (MSK), so her new photos
    show it and her replies mention it; «Надеть сегодня» switches later,
  * lifts her mood meter and gives relationship points like a gift.
Room things never come off: they sit in the background of her home photos and
in her small stories. The kitten gets a name from him.

No guilt mechanics on purpose (audience: lonely men looking for warmth): the
mood only drifts back to calm, she never gets sad because nothing was bought
and never asks for presents. 18+ items are Premium + confirmed 18+ only, like
the rest of intimacy (services/intimacy_gate.py).

Prompt budget: an outfit adds one ~150-char WARDROBE value in place of the pool
pick, room things add one short STORY DETAIL. SpicyAPI's 5000-char cap is kept
by private_photo_service._fit_spicy_prompt as for every other photo.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from models.app_models import WardrobeOwned, WardrobeState, utcnow
from services.db import SessionLocal

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

MOOD_BASE = 50
MOOD_WEAR_BONUS = 30
MOOD_ROOM_BONUS = 15
MOOD_DRIFT_PER_HOUR = 1.0  # back toward MOOD_BASE, never below it
WEAR_RELATIONSHIP = 1.5
ROOM_RELATIONSHIP = 1.0
PET_NAME_MAX = 20

from services.wardrobe_catalog import (  # noqa: F401  (re-exported)
    ADULT_SCENES, CASUAL, EVENING, HOME, ITEMS, PETS, PHOTO_SLOTS_MAX, ROOM_SCENES, SECTION_TITLES, SECTIONS,
    SLOTS, SPORT, STYLE_CHANGE_PRICE, STYLES, Item, Style, _BY_ID, style as get_style,
)
import json


def get(item_id: str) -> Item | None:
    return _BY_ID.get(str(item_id or ''))


def card_art(item_id: str) -> str:
    """File name of the catalogue card picture under webapp/art/ (may be missing)."""
    return f'wd_{item_id}.jpg'


def _today() -> str:
    return datetime.now(MSK).date().isoformat()


# ── storage ───────────────────────────────────────────────────────────────

def owned_ids(telegram_id: int, character_id: str) -> list[str]:
    try:
        with SessionLocal() as s:
            rows = s.scalars(select(WardrobeOwned.item_id).where(
                WardrobeOwned.telegram_id == int(telegram_id),
                WardrobeOwned.character_id == str(character_id))).all()
        return [r for r in rows if r in _BY_ID]
    except Exception:
        logger.exception('wardrobe owned read failed user=%s', telegram_id)
        return []


def _state(s, telegram_id: int, character_id: str, create: bool = False) -> WardrobeState | None:
    st = s.get(WardrobeState, (int(telegram_id), str(character_id)))
    if st is None and create:
        st = WardrobeState(telegram_id=int(telegram_id), character_id=str(character_id),
                           mood=MOOD_BASE, mood_at=utcnow())
        s.add(st)
    return st


def _mood_now(st: WardrobeState | None, now: datetime | None = None) -> int:
    if st is None or st.mood is None:
        return MOOD_BASE
    now = now or utcnow()
    hours = max(0.0, (now - (st.mood_at or now)).total_seconds() / 3600.0)
    value = max(MOOD_BASE, float(st.mood) - hours * MOOD_DRIFT_PER_HOUR)
    return int(round(min(100.0, value)))


def mood(telegram_id: int, character_id: str) -> int:
    try:
        with SessionLocal() as s:
            return _mood_now(_state(s, telegram_id, character_id))
    except Exception:
        return MOOD_BASE


def mood_label(value: int, lang: str = 'ru') -> str:
    if value >= 80:
        return 'happy' if lang == 'en' else 'счастлива'
    if value >= 62:
        return 'in a good mood' if lang == 'en' else 'в хорошем настроении'
    return 'calm' if lang == 'en' else 'спокойная'


def worn_today(telegram_id: int, character_id: str) -> Item | None:
    try:
        with SessionLocal() as s:
            st = _state(s, telegram_id, character_id)
            if st is None or not st.worn_item or st.worn_day != _today():
                return None
            return _BY_ID.get(st.worn_item)
    except Exception:
        return None


def pet_name(telegram_id: int, character_id: str) -> str:
    try:
        with SessionLocal() as s:
            st = _state(s, telegram_id, character_id)
            return (st.pet_name or '') if st else ''
    except Exception:
        return ''


def clean_pet_name(raw: str) -> str:
    t = re.sub(r'[^\w \-ёЁ]', '', str(raw or ''), flags=re.U)
    return re.sub(r'\s+', ' ', t).strip()[:PET_NAME_MAX]


def can_buy_adult(*, premium: bool, adult: bool, admin: bool = False) -> bool:
    return admin or (premium and adult)


def grant(telegram_id: int, character_id: str, item_id: str) -> bool:
    """Record the purchase (money is taken by the caller), put a garment on for
    today and lift her mood. False when she already has it or on a DB error."""
    item = _BY_ID.get(item_id)
    if not item:
        return False
    try:
        with SessionLocal() as s:
            if s.get(WardrobeOwned, (int(telegram_id), str(character_id), item.id)):
                return False
            s.add(WardrobeOwned(telegram_id=int(telegram_id), character_id=str(character_id), item_id=item.id))
            st = _state(s, telegram_id, character_id, create=True)
            now = utcnow()
            bonus = MOOD_ROOM_BONUS if item.kind == 'room' else MOOD_WEAR_BONUS
            st.mood = min(100, _mood_now(st, now) + bonus)
            st.mood_at = now
            if item.kind in ('wear', 'adult'):
                st.worn_item = item.id
                st.worn_day = _today()
            elif item.slot:
                slots = _slots(st)
                slots[item.slot] = item.id
                st.room_slots_json = json.dumps(slots)
            s.commit()
        return True
    except Exception:
        logger.exception('wardrobe grant failed user=%s item=%s', telegram_id, item_id)
        return False


def wear(telegram_id: int, character_id: str, item_id: str) -> bool:
    """«Надеть сегодня»: an owned garment for the rest of the MSK day; '' takes it off."""
    if item_id and (item_id not in _BY_ID or _BY_ID[item_id].kind not in ('wear', 'adult')):
        return False
    if item_id and item_id not in owned_ids(telegram_id, character_id):
        return False
    try:
        with SessionLocal() as s:
            st = _state(s, telegram_id, character_id, create=True)
            st.worn_item = item_id or None
            st.worn_day = _today() if item_id else None
            s.commit()
        return True
    except Exception:
        logger.exception('wardrobe wear failed user=%s item=%s', telegram_id, item_id)
        return False


def set_pet_name(telegram_id: int, character_id: str, name: str) -> str:
    name = clean_pet_name(name)
    if not name or not (PETS & set(owned_ids(telegram_id, character_id))):
        return ''
    try:
        with SessionLocal() as s:
            st = _state(s, telegram_id, character_id, create=True)
            st.pet_name = name
            s.commit()
        return name
    except Exception:
        logger.exception('wardrobe pet name failed user=%s', telegram_id)
        return ''


# ── what the Mini App shows ───────────────────────────────────────────────

def catalog(telegram_id: int, character_id: str, lang: str = 'ru', *, adult_open: bool = False) -> dict:
    owned = set(owned_ids(telegram_id, character_id))
    worn = worn_today(telegram_id, character_id)
    m = mood(telegram_id, character_id)
    sections = []
    for sec in SECTIONS:
        items = [{
            'id': i.id, 'emoji': i.emoji, 'title': i.en if lang == 'en' else i.ru, 'price': i.price,
            'kind': i.kind, 'owned': i.id in owned, 'worn': bool(worn and worn.id == i.id),
            'locked': i.kind == 'adult' and not adult_open,
            'wearable': i.kind in ('wear', 'adult'), 'art': f'/webapp/art/{card_art(i.id)}',
        } for i in ITEMS if i.section == sec]
        t = SECTION_TITLES[sec]
        sections.append({'key': sec, 'title': t[1] if lang == 'en' else t[0], 'items': items})
    room_total = sum(1 for i in ITEMS if i.kind == 'room')
    return {
        'mood': m, 'mood_label': mood_label(m, lang),
        'owned_wear': sum(1 for i in owned if _BY_ID[i].kind != 'room'),
        'total_wear': len(ITEMS) - room_total,
        'owned_room': sum(1 for i in owned if _BY_ID[i].kind == 'room'), 'total_room': room_total,
        'worn': worn.id if worn else '', 'pet_name': pet_name(telegram_id, character_id),
        'sections': [x for x in sections if x['key'] != 'room'],
        'home': home_catalog(telegram_id, character_id, lang, list(owned)),
    }


# ── photos ────────────────────────────────────────────────────────────────

def photo_overrides(telegram_id: int, character_id: str, scene: str, group: str) -> dict:
    """Fields for photo_service._resolve_request. Keys (all optional):
    clothing, accessory, underwear, room. Fail-silent: {} on any error."""
    try:
        owned = owned_ids(telegram_id, character_id)
        if not owned:
            return {}
        out: dict = {}
        worn = worn_today(telegram_id, character_id)
        if worn and worn.kind == 'wear' and group in worn.groups:
            out['clothing'] = worn.prompt
        elif worn and worn.kind == 'adult':
            if scene in ADULT_SCENES:
                out['clothing'] = worn.prompt
            out['underwear'] = worn.prompt  # used when the home-lingerie rule kicks in
        jewels = [_BY_ID[i].prompt for i in owned if _BY_ID[i].kind == 'jewel']
        if jewels:
            out['accessory'] = ' and '.join(jewels)
        if scene in ROOM_SCENES:
            home = home_state(telegram_id, character_id, owned)
            st_ = get_style(home['style'])
            things = [_BY_ID[i].prompt for i in home['active'][:PHOTO_SLOTS_MAX]]
            if st_ or things:
                out['room'] = 'her room: ' + '; '.join(([st_.prompt] if st_ else []) + things)
        return out
    except Exception:
        logger.exception('wardrobe photo overrides failed user=%s', telegram_id)
        return {}


# ── chat ──────────────────────────────────────────────────────────────────

def chat_line(telegram_id: int, character_id: str) -> str:
    """A short note for her system prompt; '' when he gave her nothing."""
    try:
        owned = owned_ids(telegram_id, character_id)
        if not owned:
            return ''
        parts = []
        worn = worn_today(telegram_id, character_id)
        if worn:
            parts.append(f'сегодня на тебе {worn.say} — его подарок')
        jewels = [_BY_ID[i].say for i in owned if _BY_ID[i].kind == 'jewel']
        if jewels:
            parts.append('ты носишь его ' + ' и '.join(jewels))
        home = home_state(telegram_id, character_id, owned)
        st_ = get_style(home['style'])
        if st_:
            parts.append(f'твоя комната — {st_.say}, вы обставляете её вместе')
        if home['active']:
            names = []
            for iid in home['active']:
                i = _BY_ID[iid]
                if i.id in PETS:
                    pn = pet_name(telegram_id, character_id)
                    names.append(f'{i.say} {pn}' if pn else f'{i.say} (он ещё не дал имя — можешь попросить придумать)')
                else:
                    names.append(i.say)
            parts.append('у тебя в комнате его подарки: ' + ', '.join(names))
        other = [_BY_ID[i].say for i in owned if _BY_ID[i].kind in ('wear', 'adult') and (not worn or i != worn.id)]
        if other:
            parts.append('в шкафу ещё его подарки: ' + ', '.join(other[:6]))
        m = mood(telegram_id, character_id)
        mood_note = (' Ты сейчас счастлива после его подарка: чуть теплее и игривее обычного.' if m >= 80 else '')
        return ('ЕГО ПОДАРКИ (правда твоей жизни): ' + '; '.join(parts) + '.' + mood_note +
                ' Упоминай это естественно и изредка, когда к слову (не в каждом ответе): как тебе в этой вещи, '
                'что делает питомец, как теперь в комнате. Никогда не проси новых подарков, не намекай на покупки '
                'и не обижайся, что он чего-то не подарил.')
    except Exception:
        logger.exception('wardrobe chat line failed user=%s', telegram_id)
        return ''


def gift_action(item: Item, lang: str = 'ru') -> str:
    """His side of the gift, saved as his message in the chat."""
    if lang == 'en':
        return f'*gives you a present: {item.en.lower()}* 🎁'
    return f'*дарю тебе подарок: {item.ru.lower()}* 🎁'


def gift_scene(item: Item, name: str = '') -> str:
    who = name or 'она'
    if item.kind == 'room':
        what = f'вещь для твоей комнаты — {item.say}'
        tail = 'Скажи, куда поставишь или повесишь, и как теперь будет уютно.'
        if item.id == 'kitten':
            what = 'маленького пушистого котёнка'
            tail = 'Ты в восторге, возишься с ним и просишь его придумать котёнку имя.'
    else:
        what = item.say
        tail = 'Скажи, что сейчас примеришь и пришлёшь фото, как сидит.'
    return (f'СЦЕНА ПОДАРКА: он только что подарил тебе, {who}, {what}. Отреагируй живо и по-настоящему: '
            f'удивление, радость, пару деталей, почему тебе это нравится. {tail} '
            '2-4 коротких предложения, без пафоса и без просьб о новых подарках.')


# ── V3.116.0: «🏠 Дом» — she gets an empty room in a style he picks, and he
# furnishes it place by place. Every purchase redraws the room picture FROM THE
# PREVIOUS ONE (edit, not a fresh render), so it stays the same room.
HOME_REDRAW_PRICE = 200  # putting back a thing she already has = one new picture


def _slots(st) -> dict:
    try:
        data = json.loads(st.room_slots_json or '{}') if st is not None else {}
        return {k: v for k, v in data.items() if v in _BY_ID and _BY_ID[v].slot == k}
    except Exception:
        return {}


def home_state(telegram_id: int, character_id: str, owned: list[str] | None = None) -> dict:
    """{'style', 'image', 'slots': {slot: item_id}, 'active': [item_id ordered by SLOTS]}.
    Room things bought before V3.116.0 (no slot map yet) count as placed."""
    try:
        with SessionLocal() as s:
            st = _state(s, telegram_id, character_id)
            style_id = (st.room_style or '') if st else ''
            image = (st.room_image or '') if st else ''
            slots = _slots(st)
    except Exception:
        style_id, image, slots = '', '', {}
    if not slots:
        owned = owned if owned is not None else owned_ids(telegram_id, character_id)
        for iid in owned:
            it = _BY_ID.get(iid)
            if it and it.slot:
                slots[it.slot] = iid
    active = [slots[k] for k, _ru, _en in SLOTS if k in slots]
    return {'style': style_id, 'image': image, 'slots': slots, 'active': active}


def set_style(telegram_id: int, character_id: str, style_id: str) -> bool:
    if not get_style(style_id):
        return False
    try:
        with SessionLocal() as s:
            st = _state(s, telegram_id, character_id, create=True)
            st.room_style = style_id
            s.commit()
        return True
    except Exception:
        logger.exception('home style failed user=%s', telegram_id)
        return False


def place(telegram_id: int, character_id: str, item_id: str) -> bool:
    """Put back an owned room thing in its place."""
    it = _BY_ID.get(item_id)
    if not it or not it.slot or item_id not in owned_ids(telegram_id, character_id):
        return False
    try:
        with SessionLocal() as s:
            st = _state(s, telegram_id, character_id, create=True)
            slots = home_state(telegram_id, character_id)['slots']
            slots[it.slot] = it.id
            st.room_slots_json = json.dumps(slots)
            s.commit()
        return True
    except Exception:
        logger.exception('home place failed user=%s', telegram_id)
        return False


def set_room_image(telegram_id: int, character_id: str, filename: str) -> None:
    try:
        with SessionLocal() as s:
            st = _state(s, telegram_id, character_id, create=True)
            st.room_image = filename
            s.commit()
    except Exception:
        logger.exception('home image save failed user=%s', telegram_id)


ROOM_QUALITY = (' Photorealistic interior photo shot on a phone, wide angle from the doorway, eye level, natural '
                'light, cozy lived-in feeling, no people, no text, no watermark, no logo.')


def room_prompt_full(style_id: str, active: list[str]) -> str:
    st_ = get_style(style_id)
    base = f'Interior of a young woman\'s bedroom: {st_.prompt if st_ else "a cozy bedroom"}.'
    if active:
        base += ' In the room: ' + '; '.join(_BY_ID[i].prompt for i in active) + '.'
    else:
        base += ' The room is still almost empty: only a simple mattress on the floor, bare walls and a window.'
    return base + ROOM_QUALITY


def room_prompt_edit(item_id: str, replaced: str = '') -> str:
    it = _BY_ID[item_id]
    swap = (f' It replaces {_BY_ID[replaced].prompt}, which is removed.' if replaced and replaced in _BY_ID else '')
    return ('The same room as in the reference image: keep the exact walls, floor, window, camera angle, light and '
            f'every other object unchanged. Add {it.prompt} in a natural place.{swap}' + ROOM_QUALITY)


def home_catalog(telegram_id: int, character_id: str, lang: str = 'ru', owned: list[str] | None = None) -> dict:
    owned = owned if owned is not None else owned_ids(telegram_id, character_id)
    home = home_state(telegram_id, character_id, owned)
    en = lang == 'en'
    slots = []
    for key, ru, en_t in SLOTS:
        slots.append({'key': key, 'title': en_t if en else ru, 'items': [{
            'id': i.id, 'emoji': i.emoji, 'title': i.en if en else i.ru, 'price': i.price,
            'owned': i.id in owned, 'active': home['slots'].get(key) == i.id, 'pet': i.id in PETS,
            'art': f'/webapp/art/{card_art(i.id)}',
        } for i in ITEMS if i.slot == key]})
    return {
        'style': home['style'],
        'image': f'/webapp/media/{home["image"]}' if home['image'] else '',
        'styles': [{'id': x.id, 'emoji': x.emoji, 'title': x.en if en else x.ru,
                    'art': f'/webapp/art/home_{x.id}.jpg'} for x in STYLES],
        'style_price': STYLE_CHANGE_PRICE, 'redraw_price': HOME_REDRAW_PRICE,
        'slots': slots,
    }
