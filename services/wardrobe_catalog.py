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
    slot: str = ''         # V3.116.0: «🏠 Дом» — the place in her room this thing takes


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
    # ── V3.116.0: «🏠 Дом» — furniture by place; one active thing per place ──
    # bed
    Item('bed_soft', 'room', 'room', '🛏', 'Кровать с мягким изголовьем', 'Bed with a soft headboard', 600,
         'a wide bed with a tall soft upholstered headboard and white linen', 'кровать с мягким изголовьем',
         tryon='home', slot='bed'),
    Item('bed_round', 'room', 'room', '⭕', 'Круглая кровать', 'Round bed', 2000,
         'a big round bed with satin sheets and many pillows', 'круглая кровать', tryon='home', slot='bed'),
    Item('canopy', 'room', 'room', '🏰', 'Кровать с балдахином', 'Canopy bed', 3000,
         'a big bed with a sheer white canopy', 'кровать с балдахином', tryon='home', slot='bed'),
    # bedding
    Item('blanket', 'room', 'room', '🧶', 'Плед и подушки', 'Throw and pillows', 400,
         'a chunky knit throw blanket and soft pillows on the bed', 'плед и подушки', tryon='home', slot='textile'),
    Item('silk_sheets', 'room', 'room', '🥀', 'Шёлковое бельё', 'Silk sheets', 800,
         'deep red silk sheets on the bed', 'шёлковое постельное бельё', tryon='home', slot='textile'),
    # seat
    Item('beanbag', 'room', 'room', '🫘', 'Кресло-мешок', 'Bean bag chair', 500,
         'a big soft bean bag chair', 'кресло-мешок', tryon='home', slot='seat'),
    Item('egg_chair', 'room', 'room', '🪺', 'Кресло-кокон', 'Hanging egg chair', 1200,
         'a hanging rattan egg chair with a white cushion in the corner', 'кресло-кокон', tryon='home', slot='seat'),
    Item('sofa_velvet', 'room', 'room', '🛋', 'Бархатный диван', 'Velvet sofa', 1500,
         'a curved velvet sofa', 'бархатный диван', tryon='home', slot='seat'),
    # light
    Item('lights', 'room', 'room', '✨', 'Гирлянда над кроватью', 'Fairy lights', 300,
         'warm fairy lights strung above the bed', 'гирлянда над кроватью', tryon='home', slot='light'),
    Item('candles', 'room', 'room', '🕯', 'Свечи', 'Candles', 500,
         'many lit candles giving a warm glow', 'свечи', tryon='home', slot='light'),
    Item('starlamp', 'room', 'room', '🌌', 'Ночник «звёздное небо»', 'Starry sky lamp', 600,
         'a star projector night lamp casting soft stars on the walls', 'ночник «звёздное небо»', tryon='home', slot='light'),
    Item('neon_heart', 'room', 'room', '💗', 'Неоновое сердце', 'Neon heart', 800,
         'a pink neon heart sign glowing on the wall', 'неоновое сердце на стене', tryon='home', slot='light'),
    # wall
    Item('tapestry', 'room', 'room', '🖼', 'Гобелен на стену', 'Wall tapestry', 500,
         'a large patterned tapestry on the wall', 'гобелен на стене', tryon='home', slot='wall'),
    Item('mirror_gold', 'room', 'room', '🪞', 'Зеркало в золотой раме', 'Gold-framed mirror', 900,
         'a tall mirror in an ornate gold frame', 'зеркало в золотой раме', tryon='home', slot='wall'),
    Item('wall_photos', 'room', 'room', '📷', 'Стена с фотками', 'Photo wall', 700,
         'a wall of small framed photos and polaroids with string lights', 'стена с нашими фотками', tryon='home', slot='wall'),
    # floor
    Item('rug_fluffy', 'room', 'room', '☁️', 'Пушистый ковёр', 'Fluffy rug', 400,
         'a big white fluffy rug on the floor', 'пушистый ковёр', tryon='home', slot='floor'),
    Item('rug_persian', 'room', 'room', '🧿', 'Персидский ковёр', 'Persian rug', 900,
         'an ornate red and gold Persian rug on the floor', 'персидский ковёр', tryon='home', slot='floor'),
    # plants
    Item('flowers', 'room', 'room', '💐', 'Цветы в вазе', 'Flowers in a vase', 300,
         'a vase of fresh pink peonies on the nightstand', 'цветы в вазе', tryon='home', slot='plants'),
    Item('monstera', 'room', 'room', '🪴', 'Монстера', 'Monstera', 500,
         'a big monstera plant in a ceramic pot', 'монстера в горшке', tryon='home', slot='plants'),
    Item('orchids', 'room', 'room', '🌸', 'Орхидеи', 'Orchids', 700,
         'white orchids on the windowsill', 'орхидеи на подоконнике', tryon='home', slot='plants'),
    # pet
    Item('kitten', 'room', 'room', '🐈', 'Котёнок', 'Kitten', 2500,
         'her small fluffy grey kitten curled up nearby', 'котёнок', tryon='home', slot='pet'),
    Item('puppy', 'room', 'room', '🐕', 'Щенок шпица', 'Pomeranian puppy', 2500,
         'her tiny fluffy cream Pomeranian puppy nearby', 'щенок шпица', tryon='home', slot='pet'),
)

_BY_ID = {i.id: i for i in ITEMS}
SECTIONS = ('daily', 'out', 'jewel', 'adult', 'room')
SECTION_TITLES = {
    'daily': ('Домашнее и повседневное', 'Everyday'),
    'out': ('На выход', 'Going out'),
    'jewel': ('Украшения', 'Jewellery'),
    'adult': ('Для двоих · 18+', 'For two · 18+'),
    'room': ('Дом', 'Her home'),
}


# V3.116.0: «🏠 Дом» — places in her room (order = what shows first in photos)
SLOTS: tuple[tuple[str, str, str], ...] = (
    ('bed', 'Кровать', 'Bed'),
    ('light', 'Свет', 'Light'),
    ('pet', 'Питомец', 'Pet'),
    ('seat', 'Кресло или диван', 'Seat'),
    ('wall', 'Стена', 'Wall'),
    ('plants', 'Растения', 'Plants'),
    ('textile', 'Постель', 'Bedding'),
    ('floor', 'Пол', 'Floor'),
)
PHOTO_SLOTS_MAX = 5  # how many places her photos mention (prompt budget)
PETS = frozenset({'kitten', 'puppy'})


@dataclass(frozen=True)
class Style:
    id: str
    emoji: str
    ru: str
    en: str
    prompt: str
    say: str


# the first style is free; a change later costs STYLE_CHANGE_PRICE (one new render)
STYLE_CHANGE_PRICE = 500
STYLES: tuple[Style, ...] = (
    Style('modern', '🏙', 'Современная', 'Modern',
          'a modern minimalist city apartment bedroom with light grey walls, a big window with a city view and a light oak floor',
          'современная комната в городской квартире'),
    Style('scandi', '🌿', 'Скандинавская', 'Scandinavian',
          'a cozy Scandinavian bedroom with white walls, a pale wooden floor, linen textures and soft daylight from a big window',
          'светлая скандинавская комната'),
    Style('loft', '🧱', 'Лофт', 'Loft',
          'an industrial loft bedroom with a red brick wall, black metal window frames, concrete floor and high ceilings',
          'лофт с кирпичной стеной'),
    Style('arabic', '🕌', 'Арабская', 'Arabic',
          'an elegant Arabic-style bedroom with carved wooden lattice screens, arched windows, brass lanterns, warm sand-colored walls and rich jewel-tone fabrics',
          'комната в арабском стиле с резными ширмами и фонарями'),
    Style('indian', '🪷', 'Индийская', 'Indian',
          'a vibrant Indian-style bedroom with warm saffron and magenta walls, carved wooden furniture, brass details, colorful embroidered cushions and marigold accents',
          'яркая комната в индийском стиле'),
    Style('japanese', '🎋', 'Японская', 'Japanese',
          'a calm Japanese-style bedroom with tatami flooring, shoji paper sliding doors, low wooden furniture and a view of a small garden',
          'японская комната с татами и сёдзи'),
    Style('romantic', '🎀', 'Романтичная', 'Romantic',
          'a soft romantic bedroom with blush pink walls, white wood panelling, lace curtains and a crystal chandelier',
          'нежная розовая романтичная комната'),
    Style('luxury', '💎', 'Роскошная', 'Luxury',
          'a luxury penthouse bedroom with marble floor, dark walnut walls, gold accents and a floor-to-ceiling window with a night skyline',
          'роскошный пентхаус с мраморным полом'),
)
_STYLE_BY_ID = {x.id: x for x in STYLES}


def style(style_id: str) -> Style | None:
    return _STYLE_BY_ID.get(str(style_id or ''))
