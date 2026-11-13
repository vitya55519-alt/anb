"""V3.153.0: owner ТЗ (Фогель, Модуль 4) — «🎁 Подарки»: four cheap gifts whose
point is that they stay on her.

The wardrobe (V3.114.0) lends a garment for the MSK day and pays for a try-on
render, so it starts at 300 🍑. This is the impulse tier next to it: 100–400 🍑,
and what he buys keeps working after the day is over —

  * the last gift she was given is her `current_outfit` forever (until the next
    one replaces it), and its English clause rides into every later photo
    through photo_service._resolve_request, so a paid gift visibly changes the
    picture;
  * the two behavioral gifts fill a counter of her own replies: the БДСМ-сет
    pushes his chosen manner to the «Страсть» end, the wine takes her shyness
    off. The wine only moves the LEVEL gate — Premium and the 18+ confirmation
    stay exactly as the owner set them (V3.90.0 «весь интим только с премиумом»),
    and a glass still does something for a free user: she gets warm and
    chatty, which is what he paid for.
  * «автоматически при покупке дорогого подарка»: only a gift at or above
    GIFT_AUTO_PHOTO_MIN_PEACHES renders its own picture, because a render is
    ~250 🍑 of our money and 150 🍑 cannot pay for one;
  * the wine is the one repeat sale: there is nothing to keep, so after the
    counter runs out he buys the next bottle (the same counter just refills).

Money is taken by the caller (main.py), the same way the wardrobe does it, so a
failed write can put the peaches back.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from config import (
    GIFT_AUTO_PHOTO_MIN_PEACHES, GIFT_COLLAR_PEACHES, GIFT_LACE_PEACHES,
    GIFT_LATEX_PEACHES, GIFT_PASSION_TURNS, GIFT_POINTS_SCALE,
    GIFT_WINE_MIN_LEVEL, GIFT_WINE_PEACHES, GIFT_WINE_TURNS,
)
from models.app_models import GiftOwned, GiftState, utcnow
from services.db import SessionLocal

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

# Scenes where she is naked on purpose: a gift never puts clothes back over
# them, it only says what she took off.
NUDE_SCENES = frozenset({'nude', 'morning_nude', 'topless', 'shower', 'bath', 'explicit'})


@dataclass(frozen=True)
class Gift:
    id: str
    emoji: str
    ru: str
    en: str
    price: int            # peaches
    points: int           # «очки к прогрессу уровня» from the ТЗ (scaled below)
    outfit: str = ''      # English clause for the photo prompt; '' = nothing to wear
    say: str = ''         # Russian, how she calls it in the chat
    slot: str = 'clothing'  # 'clothing' | 'accessory' | 'none'
    outer_groups: frozenset = field(default_factory=frozenset)   # scene groups worn on top
    outer_scenes: frozenset = field(default_factory=frozenset)   # scenes worn on top
    adult: bool = False   # Premium + confirmed 18+ to buy, like the wardrobe 18+
    turns: str = ''       # '' | 'wine' | 'passion' — which counter the gift fills
    tryon: str = 'mirror'  # scene of the try-on picture for an expensive gift
    art: str = ''         # an existing app picture for the card; '' = the emoji


GIFTS: tuple[Gift, ...] = (
    Gift('lace', '👙', 'Красное кружевное бельё', 'Red lace lingerie', GIFT_LACE_PEACHES, 20,
         'wearing only a red lace lingerie set — a delicate balconette bra and matching panties',
         'красное кружевное бельё', 'clothing',
         frozenset({'home'}), frozenset({'mirror', 'car'}),
         adult=True, art='wd_lace.jpg'),
    Gift('latex', '👗', 'Откровенное латексное мини-платье', 'Revealing latex mini dress', GIFT_LATEX_PEACHES, 35,
         'a skintight black latex mini dress with a deep neckline, sheer black stockings and stiletto heels',
         'латексное мини-платье', 'clothing',
         frozenset({'home', 'evening', 'fashion'}), frozenset(),
         art='wd_lbd.jpg'),
    Gift('collar', '⛓', 'Ошейник и шёлковые ленты (БДСМ-сет)', 'Collar and silk ribbons', GIFT_COLLAR_PEACHES, 60,
         'a slim black leather collar with a small steel O-ring and two long silk ribbons tied at her neck',
         'ошейник с шёлковыми лентами', 'accessory',
         frozenset(), frozenset(), adult=True, turns='passion', tryon='lingerie'),
    Gift('wine', '🍾', 'Бутылка дорогого вина', 'A bottle of expensive wine', GIFT_WINE_PEACHES, 0,
         '', 'бутылка дорогого вина', 'none', frozenset(), frozenset(), turns='wine'),
)
_BY_ID = {g.id: g for g in GIFTS}


def get(gift_id: str) -> Gift | None:
    return _BY_ID.get(str(gift_id or ''))


def points_delta(points: int) -> tuple[float, float]:
    """The ТЗ level points as (relationship, intimacy) deltas for our engine."""
    rel = round(float(points) * GIFT_POINTS_SCALE, 2)
    return rel, round(rel * 0.6, 2)


def auto_photo(gift: Gift) -> bool:
    """Фогель: the picture comes free only with an expensive gift — see config."""
    return bool(gift.slot in ('clothing', 'accessory') and gift.price >= GIFT_AUTO_PHOTO_MIN_PEACHES)


def repeatable(gift: Gift) -> bool:
    """A bottle is a bottle: it has nothing to keep, so the wine is bought again
    and again — that is the only gift that is a repeat sale. Everything he can
    see on her is hers for good and is charged once."""
    return gift.slot == 'none'


# ── storage ───────────────────────────────────────────────────────────────

def _state(s, telegram_id: int, character_id: str, create: bool = False) -> GiftState | None:
    st = s.get(GiftState, (int(telegram_id), str(character_id)))
    if st is None and create:
        st = GiftState(telegram_id=int(telegram_id), character_id=str(character_id))
        s.add(st)
    return st


def owned_ids(telegram_id: int, character_id: str) -> list[str]:
    try:
        with SessionLocal() as s:
            rows = s.scalars(select(GiftOwned.gift_id).where(
                GiftOwned.telegram_id == int(telegram_id),
                GiftOwned.character_id == str(character_id))).all()
        return [r for r in rows if r in _BY_ID]
    except Exception:
        logger.exception('gifts owned read failed user=%s', telegram_id)
        return []


def worn(telegram_id: int, character_id: str) -> Gift | None:
    """The gift she is wearing now — `current_outfit` of the ТЗ. Deliberately
    never expires: the wardrobe asks «надеть сегодня», his gift stays on."""
    try:
        with SessionLocal() as s:
            st = _state(s, telegram_id, character_id)
            return _BY_ID.get(st.current_gift) if st and st.current_gift else None
    except Exception:
        return None


def current_outfit(telegram_id: int, character_id: str) -> str:
    g = worn(telegram_id, character_id)
    return g.outfit if g and g.slot != 'none' else ''


def boosts(telegram_id: int, character_id: str) -> dict:
    """{'passion': replies left, 'wine': replies left} — zero means off. The
    shop shows the countdown, the dialog only checks it is not zero. One read
    for the whole turn."""
    try:
        with SessionLocal() as s:
            st = _state(s, telegram_id, character_id)
        return {'passion': int(st.passion_left or 0) if st else 0,
                'wine': int(st.wine_left or 0) if st else 0}
    except Exception:
        return {'passion': 0, 'wine': 0}


def grant(telegram_id: int, character_id: str, gift_id: str) -> bool:
    """Record the purchase (the caller took the money), put the gift on her and
    fill the counter it carries. False when she already has a keepsake or on a DB
    error; a bottle of wine is a repeat sale and only refills its counter."""
    gift = _BY_ID.get(gift_id)
    if not gift:
        return False
    try:
        with SessionLocal() as s:
            pk = (int(telegram_id), str(character_id), gift.id)
            has = s.get(GiftOwned, pk) is not None
            if has and not repeatable(gift):
                return False
            if not has:
                s.add(GiftOwned(telegram_id=int(telegram_id), character_id=str(character_id), gift_id=gift.id))
            st = _state(s, telegram_id, character_id, create=True)
            if gift.slot in ('clothing', 'accessory'):
                st.current_gift = gift.id
            if gift.turns == 'wine':
                st.wine_left = GIFT_WINE_TURNS
            elif gift.turns == 'passion':
                st.passion_left = GIFT_PASSION_TURNS
            st.updated_at = utcnow()
            s.commit()
        return True
    except Exception:
        logger.exception('gifts grant failed user=%s gift=%s', telegram_id, gift_id)
        return False


def tick(telegram_id: int, character_id: str) -> None:
    """One of her live replies is done: the wine and the «Страсть» step down.
    Proactive pushes and ritual messages never spend his purchase."""
    try:
        with SessionLocal() as s:
            st = _state(s, telegram_id, character_id)
            if st is None or not (st.wine_left or st.passion_left):
                return
            if st.wine_left:
                st.wine_left = max(0, int(st.wine_left) - 1)
            if st.passion_left:
                st.passion_left = max(0, int(st.passion_left) - 1)
            st.updated_at = utcnow()
            s.commit()
    except Exception:
        logger.exception('gifts tick failed user=%s', telegram_id)


# ── photos ────────────────────────────────────────────────────────────────

def photo_overrides(telegram_id: int, character_id: str, scene: str, group: str) -> dict:
    """Keys for photo_service._resolve_request: 'clothing' (she wears it on top),
    'underwear' (what comes off in bed / under her clothes), 'accessory'.
    Fail-silent: {} on any error."""
    try:
        gift = worn(telegram_id, character_id)
        if not gift or not gift.outfit or gift.slot == 'none':
            return {}
        if gift.slot == 'accessory':
            # A collar goes over anything, a nude frame included.
            return {'accessory': gift.outfit}
        if scene in NUDE_SCENES:
            return {'underwear': gift.outfit}
        if group in gift.outer_groups or scene in gift.outer_scenes:
            return {'clothing': gift.outfit}
        # On the street her gift is under her clothes: PUBLIC_DRESS_RULE forbids
        # lingerie as an outfit, so putting it in WARDROBE would fight the prompt.
        return {'underwear': gift.outfit}
    except Exception:
        logger.exception('gifts photo overrides failed user=%s', telegram_id)
        return {}


# ── dialog ────────────────────────────────────────────────────────────────

def chat_line(telegram_id: int, character_id: str) -> str:
    """Her system-prompt note about his gifts; '' when he gave her nothing.
    The temporary effects are separate directives (passion_line/wine_line), so
    this stays about what she is wearing."""
    try:
        owned = owned_ids(telegram_id, character_id)
        if not owned:
            return ''
        gift = worn(telegram_id, character_id)
        parts = [f'сейчас на тебе {gift.say} — его подарок' if gift else '']
        rest = [_BY_ID[i].say for i in owned if _BY_ID[i].slot != 'none' and (not gift or i != gift.id)]
        if rest:
            parts.append('в ящике ещё его подарки: ' + ', '.join(rest[:4]))
        body = '; '.join([p for p in parts if p])
        if not body:
            return ''
        return ('ЕГО ПОДАРКИ (правда твоей жизни): ' + body +
                '. Упоминай это естественно и изредка, когда к слову: как тебе в этом, что он скажет на фото. '
                'Никогда не проси новых подарков, не намекай на покупки и не обижайся, что он чего-то не подарил.')
    except Exception:
        logger.exception('gifts chat line failed user=%s', telegram_id)
        return ''


def passion_line() -> str:
    """The БДСМ-сет: «временно переключает ползунок связи в максимум „Страсть“»."""
    return (
        'МАКСИМУМ СТРАСТИ (его подарок, держится несколько сообщений): забудь про робость и «давай не будем» — '
        'ты сама ведёшь к близости, говоришь прямо, чего хочешь, как он тебя назовёт и что наденет по его слову. '
        'Голос остаётся тёплым и живым, без грубости и без морали; детали тела — как обычно решает этап отношений.'
    )


def wine_opens_level(level: int) -> bool:
    """The wine moves the explicit-content level gate, but only from
    GIFT_WINE_MIN_LEVEL up: below it no purchase may hand out what the story
    has not reached yet."""
    try:
        return int(level or 0) >= GIFT_WINE_MIN_LEVEL
    except Exception:
        return False


def wine_line(level: int) -> str:
    """The wine as a prompt directive: a glass is always a mood, and from
    GIFT_WINE_MIN_LEVEL it is also his gift that took her shyness off."""
    if level and level < GIFT_WINE_MIN_LEVEL:
        return ('ВЗБЕДРИВШЕЕ ВИНЦО: от бокала ты раскраснелась, болтаешь смелее и ласковее, '
                'громче смеёшься, но границу приличия пока держишь.')
    return ('ВЗБЕДРИВШЕЕ ВИНЦО: от бокала ты раскраснелась, болтаешь смелее и ласковее; стеснение снято '
            'его подарком, ты держишься так, будто вы на несколько ступеней ближе. Это не отменяет '
            'его 18+ и не позволяет ничего, против чего она сама возражала.')


def gift_action(gift: Gift, lang: str = 'ru') -> str:
    """His side of the gift, saved as his message in the chat."""
    what = (gift.en if lang == 'en' else gift.ru).lower()
    if lang == 'en':
        return f'*hands you a gift: {what}* 🎁 put it on right now'
    return f'*дарю тебе подарок: {what}* 🎁 надень прямо сейчас'


def gift_scene(gift: Gift, name: str = '') -> str:
    who = name or 'она'
    if gift.slot == 'accessory':
        what = f'ошейник с шёлковыми лентами — {gift.say}'
        tail = ('В THOUGHT — как у тебя ёкает от такой вещи и как ты идёшь за ним в комнату; в MESSAGE — что '
                'уже надела и ждёшь, что он скажет. Скажи прямо, что теперь ты его.')
    elif gift.slot == 'none':
        what = f'бутылку дорогого вина — {gift.say}'
        tail = ('В THOUGHT — как ты открываешь бутылку и наливаешь два бокала, думая о нём; в MESSAGE — что '
                'первый бокал уже выпит и тебе тепло. Предложи выпить с тобой «по-настоящему», когда он приедет.')
    else:
        what = gift.say
        tail = ('В THOUGHT — как ты переодеваешься прямо сейчас перед ним: стыд, азарт, деталей в ткани; '
                'в MESSAGE — что уже в этом и как на тебе сидит, и попроси оценить.')
    return (f'СЦЕНА ПОДАРКА: он только что подарил тебе, {who}, {what}. Отреагируй живо и по-настоящему: '
            f'удивление, радость, пара деталей, почему тебе это нравится. {tail} '
            '2-4 коротких предложения, без пафоса и без просьб о новых подарках.')


# ── what the Mini App shows ───────────────────────────────────────────────

def catalog(telegram_id: int, character_id: str, lang: str = 'ru', *, adult_open: bool = False) -> dict:
    owned = set(owned_ids(telegram_id, character_id))
    gift = worn(telegram_id, character_id)
    b = boosts(telegram_id, character_id)
    en = lang == 'en'
    items = [{
        'id': g.id, 'emoji': g.emoji, 'title': g.en if en else g.ru, 'price': g.price,
        'points': g.points, 'say': g.say, 'slot': g.slot,
        'owned': g.id in owned, 'worn': bool(gift and gift.id == g.id),
        'locked': g.adult and not adult_open,
        'photo': auto_photo(g), 'repeat': repeatable(g),
        'art': f'/webapp/art/{g.art}' if g.art else '',
    } for g in GIFTS]
    return {
        'items': items,
        'worn': gift.id if gift else '',
        'worn_title': (gift.en or gift.ru) if gift else '',
        'passion': b['passion'], 'wine': b['wine'],
        'wine_turns': GIFT_WINE_TURNS, 'passion_turns': GIFT_PASSION_TURNS,
    }
