"""V3.114.0: the «👗 Гардероб» catalogue — pure data, no DB, so the one-off
card-art script (_gen_v3114_wardrobe_art.py) can import it on the owner's PC."""
from dataclasses import dataclass

# scene groups of services/photo_service.SCENE_GROUP an item is worn in
CASUAL = frozenset({'day_casual', 'home', 'fashion', 'warm_outdoor'})
EVENING = frozenset({'evening', 'fashion'})
HOME = frozenset({'home'})
SPORT = frozenset({'gym', 'warm_outdoor'})
ADULT_SCENES = frozenset({'lingerie', 'personal', 'private_fashion', 'bedroom_intimate', 'tease', 'changing_room'})
# her indoor home scenes where room things may appear in the background
ROOM_SCENES = frozenset({'home', 'mirror', 'personal', 'lingerie', 'private_fashion', 'bedroom_intimate',
                         'tease', 'changing_room', 'morning_nude'})


@dataclass(frozen=True)
class Item:
    id: str
    kind: str        # 'wear' | 'jewel' | 'adult' | 'room'
    section: str     # 'daily' | 'out' | 'jewel' | 'adult' | 'room'
    emoji: str
    ru: str
    en: str
    price: int       # peaches (new ×100 unit)
    prompt: str      # English, for the photo prompt
    say: str         # Russian, how she calls it in the chat
    groups: frozenset = frozenset()
    tryon: str = 'mirror'  # photo scene of the try-on render


ITEMS: tuple[Item, ...] = (
    # ── daily ────────────────────────────────────────────────────────────
    Item('hoodie', 'wear', 'daily', '🧥', 'Его худи оверсайз', 'His oversized hoodie', 300,
         'his oversized soft grey hoodie worn as a loose dress over bare legs, sleeves pulled over her hands',
         'его худи оверсайз', CASUAL, 'home'),
    Item('pajama', 'wear', 'daily', '💗', 'Пижама с сердечками', 'Heart pajamas', 400,
         'a cute soft pink satin pajama set with a tiny heart print, short-sleeve button top and shorts',
         'пижама с сердечками', HOME, 'home'),
    Item('jeans', 'wear', 'daily', '👖', 'Джинсы и белый топ', 'Jeans and a white top', 400,
         'high-waisted light blue straight jeans and a fitted white cotton crop top, white sneakers',
         'джинсы и белый топ', CASUAL),
    Item('sweater', 'wear', 'daily', '🧶', 'Свитер крупной вязки', 'Chunky knit sweater', 500,
         'a cozy cream chunky cable-knit oversized sweater slipping off one shoulder, with fitted dark leggings',
         'свитер крупной вязки', CASUAL, 'home'),
    Item('sport', 'wear', 'daily', '🏃‍♀️', 'Спортивный комплект', 'Sports set', 500,
         'a matching dusty-rose seamless sports bra and high-waisted leggings set, white sneakers',
         'спортивный комплект', SPORT),
    Item('sundress', 'wear', 'daily', '👗', 'Лёгкое летнее платье', 'Light summer dress', 600,
         'a light flowy white summer sundress with thin straps and a small blue floral print, knee length',
         'лёгкое летнее платье', CASUAL),
    # ── going out ────────────────────────────────────────────────────────
    Item('lbd', 'wear', 'out', '🖤', 'Маленькое чёрное платье', 'Little black dress', 1200,
         'an elegant fitted little black dress, knee length, thin straps, black heels',
         'маленькое чёрное платье', EVENING),
    Item('coat', 'wear', 'out', '🧣', 'Пальто и шарф', 'Coat and scarf', 1500,
         'a long camel wool coat over a black turtleneck and jeans, a soft red scarf, ankle boots',
         'пальто и шарф', frozenset({'day_casual', 'warm_outdoor', 'fashion'}), 'outfit'),
    Item('gown', 'wear', 'out', '✨', 'Вечернее платье в пол', 'Evening gown', 2500,
         'a floor-length emerald satin evening gown with a slit to the thigh and open shoulders, delicate heels',
         'вечернее платье в пол', EVENING, 'outfit'),
    # ── jewellery (always on once owned) ─────────────────────────────────
    Item('earrings', 'jewel', 'jewel', '💎', 'Серьги', 'Earrings', 600,
         'small sparkling diamond stud earrings', 'серьги', tryon='selfie'),
    Item('pendant', 'jewel', 'jewel', '💝', 'Кулон-сердечко', 'Heart pendant', 800,
         'a thin gold necklace with a small heart pendant', 'кулон-сердечко', tryon='selfie'),
    # ── 18+ (Premium + confirmed 18+) ────────────────────────────────────
    Item('robe', 'adult', 'adult', '🥂', 'Шёлковый халатик', 'Silk robe', 1000,
         'a short black silk robe loosely tied at the waist over matching black lace lingerie',
         'шёлковый халатик', tryon='lingerie'),
    Item('lace', 'adult', 'adult', '🌹', 'Кружевной комплект', 'Lace set', 1500,
         'a red lace lingerie set, delicate balconette bra and matching panties',
         'кружевной комплект', tryon='lingerie'),
    Item('stockings', 'adult', 'adult', '🖤', 'Чулки с поясом', 'Stockings and garter', 1500,
         'black lace lingerie with a garter belt and sheer black stockings',
         'чулки с поясом', tryon='lingerie'),
    Item('bodysuit', 'adult', 'adult', '🤍', 'Боди', 'Bodysuit', 2000,
         'a white sheer lace bodysuit with a plunging neckline',
         'кружевное боди', tryon='lingerie'),
    # ── room ─────────────────────────────────────────────────────────────
    Item('lights', 'room', 'room', '✨', 'Гирлянда над кроватью', 'Fairy lights', 300,
         'warm fairy lights strung above her bed', 'гирлянда над кроватью', tryon='home'),
    Item('flowers', 'room', 'room', '💐', 'Цветы в вазе', 'Flowers in a vase', 300,
         'a vase of fresh pink peonies on her nightstand', 'цветы в вазе', tryon='home'),
    Item('blanket', 'room', 'room', '🛋', 'Плед и подушки', 'Throw and pillows', 400,
         'a chunky knit throw blanket and soft pillows on her bed', 'плед и подушки', tryon='home'),
    Item('candles', 'room', 'room', '🕯', 'Свечи', 'Candles', 500,
         'a few lit candles giving a warm glow', 'свечи', tryon='home'),
    Item('starlamp', 'room', 'room', '🌌', 'Ночник «звёздное небо»', 'Starry sky lamp', 600,
         'a star projector night lamp casting soft stars on the wall', 'ночник «звёздное небо»', tryon='home'),
    Item('egg_chair', 'room', 'room', '🪺', 'Кресло-кокон', 'Hanging egg chair', 1200,
         'a hanging rattan egg chair with a white cushion in the corner', 'кресло-кокон', tryon='home'),
    Item('kitten', 'room', 'room', '🐈', 'Котёнок', 'Kitten', 2500,
         'her small fluffy grey kitten curled up nearby', 'котёнок', tryon='home'),
    Item('canopy', 'room', 'room', '🛏', 'Кровать с балдахином', 'Canopy bed', 3000,
         'a big bed with a sheer white canopy', 'кровать с балдахином', tryon='home'),
)

_BY_ID = {i.id: i for i in ITEMS}
SECTIONS = ('daily', 'out', 'jewel', 'adult', 'room')
SECTION_TITLES = {
    'daily': ('Домашнее и повседневное', 'Everyday'),
    'out': ('На выход', 'Going out'),
    'jewel': ('Украшения', 'Jewellery'),
    'adult': ('Для двоих · 18+', 'For two · 18+'),
    'room': ('Комната', 'Her room'),
}
