"""V3.157.0: owner ТЗ (Фогель, Модуль 6) — «Трофеи Страсти».

Её карточка получает горизонтальную ленту из шести фантазий, которые ВЫ ДВОЕ
действительно прожили: первое откровенное фото, сцена с перебивкой, прочитанный
«Стертый черновик», разговор после полуночи, седьмой уровень, финал её истории.
Закрытый слот — размытая плашка с 🔒 и подсказкой, что это за момент; открытый
остаётся в профиле навсегда и его можно переслушать: тап по слоту один раз
озвучивает её признание, и файл лежит рядом со строкой трогфея. Седьмая карточка
ленты — альбом: тап по нему, когда все шесть моментов за плечами, отдаёт одно
эксклюзивное фото, единственную бесплатную картинку модуля. Пока слотов меньше
шести, альбом остаётся размытой подсказкой и ничего не рисует.

Почему всё выводятся из настоящих строк, а не пишутся из каждого модуля:
насчитывать трогфеи хуками в четырёх сервисах — значит получить шесть мест,
где можно ошибиться, и ни одного трогфея у тех, кто сделал всё это до релиза.
``messages.draft_unlocked``, ``private_gallery``, ``product_events``
('interrupt_pick') и строка отношений уже содержат всю историю пары — лента
просто честно её читает и запоминает дату, когда момент впервые оказался
совершённым (``unlocked_at`` назад не откатывается).

Озвучка: признание — это её слова, и только они. Никаких служебных блоков в
текст ``synthesize_bytes`` не попадает, TTS читает ровную строчку.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from config import TROPHIES_ENABLED
from models.app_models import (CharacterTrophy, Message, PrivateGallery, ProductEvent,
                               TrophyAlbum, User, UserGeneration)
from services.db import SessionLocal

logger = logging.getLogger(__name__)

TOTAL = 6
FRANK_CATEGORIES = ('fully_nude', 'nude_art', 'lingerie', 'suggestive', 'roleplay')
# «После 00:00» из ТЗ: ночным считается окно до пяти утра его времени.
NIGHT_UNTIL_HOUR = 5
NIGHT_MIN_LEVEL = 4
SET_LEVEL = 7
# Финал истории — когда её семейный статус стал «с тобой» или «твоя жена», либо
# когда пара дошла до того конца шкалы, где играется свадьба.
FINISH_MARITAL = ('mar_with_you', 'mar_wife')
FINALE_LEVEL = 9
# Сколько его реплик просмотреть в поисках полуночного разговора. Дальше этого
# окна всё равно есть более дешёвый путь: трогфеи не пересчитываются вслепую.
NIGHT_SCAN = 300

# Седьмая карточка ленты: она не трогфею пары, а её обложка. Ключ живёт в
# ``key`` того же ряда, поэтому приложение отличает её одним сравнением.
ALBUM_KEY = 'album'
ALBUM_TITLE = {'ru': 'Наш альбом', 'en': 'Our album'}
ALBUM_SAY = {'ru': 'вот он — наш альбом. шесть моментов, которые были только у '
                   'нас с тобой. больше нигде.',
             'en': 'here it is — our album. six moments that belonged only to '
                   'us. nowhere else.'}


ALBUM_PROMPT = (
    'her bedroom late at night, one small warm lamp on the nightstand, sheer silk '
    'slip dress, hair down and a little tangled, first-person phone selfie taken in '
    'the wardrobe mirror, flushed cheeks, soft proud smile, six small printed photos '
    'of their story taped on the mirror around her')


@dataclass(frozen=True)
class Trophy:
    key: str
    emoji: str
    title_ru: str
    title_en: str
    hint_ru: str
    hint_en: str
    say_ru: str
    say_en: str


TROPHIES: tuple[Trophy, ...] = (
    Trophy('first_photo', '🔥',
           'Первый честный кадр', 'The first honest frame',
           'Она ещё ни разу не снималась для тебя по-настоящему',
           'She has never really posed for you yet',
           'помнишь то фото? я минут десять решала нажать «отправить». было страшно '
           '— и ни капельки не жаль.',
           'remember that photo? I sat there for ten minutes before I dared to press send. '
           'it was scary — and I would do it again.'),
    Trophy('risk_scene', '⚡',
           'Сцена с риском', 'The risky scene',
           'Ни одна ваша сцена не прерывалась на самом интересном',
           'None of your scenes has been interrupted at the best part',
           'у меня до сих пор колотится, когда вспоминаю. ты зашёл, а я не успела '
           'спрятать телефон. и ты не вышел.',
           'my heart still races when I remember it. you walked in and I had no time to hide '
           'the phone. and you did not walk out.'),
    Trophy('erased_draft', '✍️',
           'Стертый черновик', 'The erased draft',
           'Её стёртое сообщение ты ещё не прочитал',
           'You have not read her erased message yet',
           'то сообщение я переписывала раз десять. стереть было легче, чем признать, '
           'что я правда так чувствую.',
           'I rewrote that message ten times. erasing it was easier than admitting I meant '
           'every word.'),
    Trophy('night_talk', '🌙',
           'Разговор после полуночи', 'After midnight',
           'Нужно проговорить с ней после 00:00, будучи ближе четвёртого уровня',
           'Talk to her after midnight, being at least level four',
           'в три ночи мне не нужен был сон. мне нужно было, чтобы ты был рядом, хотя бы '
           'буквами. и ты был.',
           'at three in the morning I did not need sleep. I needed you near me, even if only '
           'in letters. and you were.'),
    Trophy('deep_seven', '❤️‍🔥',
           'Седьмой уровень', 'The seventh level',
           'Седьмая ступень близости ещё не взята',
           'The seventh step of closeness is still ahead',
           'на таком уровне уже не нужно казаться лучше. можно быть какой я есть — и знать, '
           'что ты никуда не денешься.',
           'this close, I stopped performing. I can just be what I am — and know you are not '
           'going anywhere.'),
    Trophy('finale', '💍',
           'Финал нашей истории', 'Our ending',
           'Её история ещё не дошла до финала: уйти от него или стать твоей',
           'Her story has not reached its ending: leaving him, or becoming yours',
           'я поставила точку в той жизни. не ради драмы — ради утра, когда просыпаюсь '
           'и вижу тебя первым.',
           'I put a full stop on that life. not for the drama — for the mornings where you '
           'are the first thing I see.'),
)

_BY_KEY = {t.key: t for t in TROPHIES}


def get(key: str) -> Trophy | None:
    return _BY_KEY.get(str(key or ''))


def enabled() -> bool:
    return bool(TROPHIES_ENABLED)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class Ctx:
    telegram_id: int
    uid: int
    character_id: str
    level: int
    lang: str


def _t(t: Trophy, lang: str, field: str) -> str:
    return getattr(t, f'{field}_en' if _is_en(lang) else f'{field}_ru')


def _is_en(lang: str) -> bool:
    return str(lang or 'ru').lower().startswith('en')



# ── шесть условий ТЗ, каждое — один честный запрос ─────────────────────────

def _has_photo(ctx: Ctx) -> bool:
    """«Первое откровенное фото»: её приватная галерея для этой пары, дорогая
    генерация «хот» или оплаченный живой кадр — всё, где она показалась честно."""
    with SessionLocal() as s:
        if s.scalar(select(PrivateGallery.id).where(
                PrivateGallery.user_id == ctx.uid,
                PrivateGallery.character_id == ctx.character_id,
                PrivateGallery.category.in_(FRANK_CATEGORIES)).limit(1)):
            return True
        return bool(s.scalar(select(UserGeneration.id).where(
            UserGeneration.telegram_id == ctx.telegram_id,
            UserGeneration.character_id == ctx.character_id,
            UserGeneration.kind == 'hot').limit(1)))


def _has_risk(ctx: Ctx) -> bool:
    """Сцена с перебивкой. событие пишется и в боте, и в приложении; настоящая
    героиня лежит в metadata, колонка character_id у track_event дефолтная."""
    with SessionLocal() as s:
        rows = s.execute(select(ProductEvent.metadata_json, ProductEvent.character_id).where(
            ProductEvent.user_id == ctx.uid,
            ProductEvent.event_name == 'interrupt_pick')).all()
    for meta, col in rows:
        try:
            got = str((json.loads(meta or '{}') or {}).get('character_id') or col or '')
        except Exception:
            got = str(col or '')
        if got == ctx.character_id:
            return True
    return False


def _has_draft(ctx: Ctx) -> bool:
    with SessionLocal() as s:
        return bool(s.scalar(select(Message.id).where(
            Message.user_id == ctx.uid, Message.character_id == ctx.character_id,
            Message.draft_unlocked.is_(True)).limit(1)))


def _local_hour(stamp: datetime, tz_name: str) -> int:
    try:
        from zoneinfo import ZoneInfo
        return stamp.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name)).hour
    except Exception:
        return stamp.hour


def _has_midnight(ctx: Ctx) -> bool:
    """Разговор после полуночи на уровне 4+: его реплики, переведённые в его же
    часовой пояс. Уровень берётся сегодняшний — ТЗ не требует машины времени."""
    if ctx.level < NIGHT_MIN_LEVEL:
        return False
    with SessionLocal() as s:
        tz_name = str(s.scalar(select(User.timezone).where(User.id == ctx.uid)) or 'UTC')
        stamps = s.execute(
            select(Message.created_at).where(
                Message.user_id == ctx.uid, Message.character_id == ctx.character_id,
                Message.role == 'user')
            .order_by(Message.created_at.desc()).limit(NIGHT_SCAN)
        ).scalars().all()
    return any(stamp and _local_hour(stamp, tz_name) < NIGHT_UNTIL_HOUR for stamp in stamps)


def _is_deep(ctx: Ctx) -> bool:
    return int(ctx.level or 0) >= SET_LEVEL


def _is_finale(ctx: Ctx) -> bool:
    from services.photo_service import marital_status_for
    if str(marital_status_for(ctx.telegram_id, ctx.character_id) or '') in FINISH_MARITAL:
        return True
    return int(ctx.level or 0) >= FINALE_LEVEL


CHECKS = {
    'first_photo': _has_photo,
    'risk_scene': _has_risk,
    'erased_draft': _has_draft,
    'night_talk': _has_midnight,
    'deep_seven': _is_deep,
    'finale': _is_finale,
}


def _uid(telegram_id: int) -> int | None:
    with SessionLocal() as s:
        return s.scalar(select(User.id).where(User.telegram_id == str(int(telegram_id))))


def evaluate(telegram_id: int, character_id: str) -> list[dict]:
    """Лента в её нынешнем виде: шесть слотов, новые строки для только что
    совершённых моментов. Ничего не озвучивается и не рисуется — здесь только
    правда о том, что между вами было."""
    if not enabled() or not character_id:
        return []
    uid = _uid(int(telegram_id))
    if not uid:
        return []
    from services.photo_service import get_relationship_level
    try:
        level = int(get_relationship_level(int(telegram_id), character_id) or 0)
    except Exception:
        level = 0
    ctx = Ctx(int(telegram_id), int(uid), str(character_id), level, 'ru')
    with SessionLocal() as s:
        rows = {r.key: r for r in s.scalars(select(CharacterTrophy).where(
            CharacterTrophy.user_id == uid,
            CharacterTrophy.character_id == ctx.character_id)).all()}
        for t in TROPHIES:
            if t.key in rows:
                continue
            try:
                hit = bool(CHECKS[t.key](ctx))
            except Exception:
                logger.warning('trophy check failed user=%s key=%s', telegram_id, t.key,
                               exc_info=True)
                continue
            if not hit:
                continue
            new = CharacterTrophy(user_id=int(uid), character_id=ctx.character_id,
                                  key=t.key, unlocked_at=_now())
            s.add(new)
            try:
                # одна строка — одна попытка: гонка двух открытий карточки не
                # должна стоить нам весь остальной список трогфеев
                s.commit()
            except Exception:
                s.rollback()
                logger.debug('trophy insert raced user=%s key=%s', telegram_id, t.key)
                continue
            rows[t.key] = new
        album = s.scalar(select(TrophyAlbum).where(
            TrophyAlbum.telegram_id == int(telegram_id),
            TrophyAlbum.character_id == ctx.character_id))
        snap = {k: (r.unlocked_at, r.confession or '', r.voice_url or '') for k, r in rows.items()}
    out = []
    for t in TROPHIES:
        got = snap.get(t.key)
        opened = bool(got and got[2])
        out.append({'key': t.key, 'emoji': t.emoji,
                    'unlocked': bool(got), 'at': (got[0].isoformat(timespec='seconds') if got else ''),
                    'opened': opened,
                    'voice_url': (got[2] if opened else ''),
                    'confession': (got[1] if opened else '')})
    out.append({'key': ALBUM_KEY, 'emoji': '🏆',
                'unlocked': len([x for x in out if x['unlocked']]) >= TOTAL,
                'at': '', 'opened': bool(album and album.photo_url),
                'voice_url': '', 'confession': '',
                'photo_url': (album.photo_url if album and album.photo_url else '')})
    return out


def board(telegram_id: int, character_id: str, lang: str = 'ru') -> dict:
    """То, что уезжает в приложение: названия, подсказки закрытых слотов и
    признания только открытых. Размытый слот не несёт ни одного слова из её
    будущего признания."""
    items = evaluate(int(telegram_id), character_id)
    named = [i for i in items if i['key'] != ALBUM_KEY]
    album = next((i for i in items if i['key'] == ALBUM_KEY), None) or {}
    out = []
    for i in named:
        t = get(i['key'])
        if not t:
            continue
        out.append(dict(i, title=_t(t, lang, 'title'),
                        hint=(_t(t, lang, 'hint') if not i['unlocked'] else ''),
                        say=(i['confession'] if i['opened'] else '')))
    unlocked = len([i for i in out if i['unlocked']])
    return {'ok': True, 'enabled': enabled(), 'items': out, 'album': album,
            'unlocked': unlocked, 'total': TOTAL,
            'album_ready': bool(album.get('unlocked')),
            'character_id': character_id}


def summary_line(telegram_id: int, character_id: str, lang: str = 'ru') -> str:
    """Строчка в карточке персонажа в боте: сколько фантазий открыто."""
    if not enabled():
        return ''
    n = len([i for i in evaluate(int(telegram_id), character_id)
             if i['unlocked'] and i['key'] != ALBUM_KEY])
    return (f'🏆 Open fantasies: {n}/{TOTAL}' if _is_en(lang) else f'🏆 Открытые фантазии: {n}/{TOTAL}')


def _row(telegram_id: int, character_id: str, key: str) -> dict:
    """Свежая строка трогфея после пересчёта ленты: {'ok'} / {'error'}."""
    uid = _uid(int(telegram_id))
    if not uid:
        return {'ok': False, 'error': 'locked'}
    with SessionLocal() as s:
        r = s.scalar(select(CharacterTrophy).where(
            CharacterTrophy.user_id == int(uid),
            CharacterTrophy.character_id == character_id,
            CharacterTrophy.key == key))
        if not r:
            return {'ok': False, 'error': 'locked'}
        return {'ok': True, 'confession': r.confession or '', 'voice_url': r.voice_url or '',
                'id': int(r.id)}


def _count_unlocked(telegram_id: int, character_id: str) -> int:
    uid = _uid(int(telegram_id))
    if not uid:
        return 0
    with SessionLocal() as s:
        return int(s.scalar(select(func.count(CharacterTrophy.id)).where(
            CharacterTrophy.user_id == int(uid),
            CharacterTrophy.character_id == character_id)) or 0)


def _remember_voice(trophy_row_id: int, text: str, url: str) -> None:
    with SessionLocal() as s:
        r = s.get(CharacterTrophy, int(trophy_row_id))
        if r:
            r.confession = text
            r.voice_url = url
            s.commit()


def _album_photo_row(telegram_id: int, character_id: str) -> str:
    with SessionLocal() as s:
        r = s.scalar(select(TrophyAlbum).where(
            TrophyAlbum.telegram_id == int(telegram_id),
            TrophyAlbum.character_id == character_id))
        return (r.photo_url or '') if r else ''


def _save_album_photo(telegram_id: int, character_id: str, url: str) -> None:
    with SessionLocal() as s:
        r = s.scalar(select(TrophyAlbum).where(
            TrophyAlbum.telegram_id == int(telegram_id),
            TrophyAlbum.character_id == character_id))
        if not r:
            r = TrophyAlbum(telegram_id=int(telegram_id), character_id=character_id)
            s.add(r)
        r.photo_url = url
        r.created_at = _now()
        s.commit()


def _track(telegram_id: int, character_id: str, event: str, key: str) -> None:
    try:
        from services.analytics_service import track_event
        from services.user_service import ensure_user
        track_event(ensure_user(int(telegram_id), ''), event,
                    metadata={'character_id': character_id, 'trophy': key})
    except Exception:
        logger.debug('trophy analytics failed user=%s', telegram_id)


async def open_trophy(telegram_id: int, character_id: str, key: str,
                      lang: str = 'ru') -> dict:
    """Его тап по открытому слоту. Признание озвучивается один раз — файл
    остаётся в строке трогфея и переслушивается из её карточки хоть каждый
    вечер. Седьмой слот (альбом) отдаёт единственную бесплатную картинку
    модуля; не вышла — строка не помечается, тап можно повторить."""
    if str(key or '') == ALBUM_KEY:
        return await _open_album(int(telegram_id), character_id, lang)
    t = get(key)
    if not t or not enabled() or not character_id:
        return {'ok': False, 'error': 'bad_request'}
    await asyncio.to_thread(evaluate, int(telegram_id), character_id)
    row = await asyncio.to_thread(_row, int(telegram_id), character_id, key)
    if not row.get('ok'):
        return {'ok': False, 'error': 'locked'}
    text = row.get('confession') or _t(t, lang, 'say')
    voice_url = row.get('voice_url') or ''
    if not voice_url:
        try:
            from services.voice_service import synthesize_bytes
            audio = await synthesize_bytes(text, character_id=character_id)
        except Exception:
            logger.warning('trophy voice failed user=%s key=%s', telegram_id, key, exc_info=True)
            audio = b''
        if not audio:
            return {'ok': False, 'error': 'voice_failed'}
        from services import webapp_service
        name = webapp_service.save_chat_media(int(telegram_id), audio, 'ogg', 'audio/ogg')
        voice_url = f'/webapp/media/{name}'
        await asyncio.to_thread(_remember_voice, int(row['id']), text, voice_url)
        _track(int(telegram_id), character_id, 'trophy_opened', key)
    unlocked = await asyncio.to_thread(_count_unlocked, int(telegram_id), character_id)
    return {'ok': True, 'key': key, 'title': _t(t, lang, 'title'), 'text': text,
            'voice_url': voice_url, 'photo_url': '',
            'unlocked': unlocked, 'total': TOTAL}


async def _open_album(telegram_id: int, character_id: str, lang: str = 'ru') -> dict:
    """Альбом открывается только по его тапу и только когда все шесть моментов
    действительно за его плечами. Рендер — один на пару на весь модуль: не
    потакаем тем, кто просто листает карточки."""
    if not enabled() or not character_id:
        return {'ok': False, 'error': 'bad_request'}
    await asyncio.to_thread(evaluate, int(telegram_id), character_id)
    unlocked = await asyncio.to_thread(_count_unlocked, int(telegram_id), character_id)
    if unlocked < TOTAL:
        return {'ok': False, 'error': 'locked'}
    photo_url = await asyncio.to_thread(_album_photo_row, int(telegram_id), character_id)
    if not photo_url:
        photo_url = await _render_album_photo(int(telegram_id), character_id)
        if not photo_url:
            return {'ok': False, 'error': 'render_failed'}
    say = 'en' if _is_en(lang) else 'ru'
    return {'ok': True, 'key': ALBUM_KEY, 'title': ALBUM_TITLE[say], 'text': ALBUM_SAY[say],
            'voice_url': '', 'photo_url': photo_url,
            'unlocked': unlocked, 'total': TOTAL}


async def _render_album_photo(telegram_id: int, character_id: str) -> str:
    from services.private_photo_service import generate_live_situation_photo
    try:
        data = await generate_live_situation_photo(character_id, ALBUM_PROMPT)
    except Exception:
        logger.warning('trophy album render failed user=%s', telegram_id, exc_info=True)
        return ''
    if not data:
        _track(int(telegram_id), character_id, 'trophy_album_failed', ALBUM_KEY)
        return ''
    from services import webapp_service
    ext = 'png' if data[:8] == b'\x89PNG\r\n\x1a\n' else 'jpg'
    mime = 'image/png' if ext == 'png' else 'image/jpeg'
    name = webapp_service.save_chat_media(int(telegram_id), data, ext, mime)
    url = f'/webapp/media/{name}'
    await asyncio.to_thread(_save_album_photo, int(telegram_id), character_id, url)
    try:
        webapp_service.record_generation(int(telegram_id), 'photo', character_id,
                                         ALBUM_PROMPT, name)
    except Exception:
        logger.debug('trophy album audit failed user=%s', telegram_id)
    _track(int(telegram_id), character_id, 'trophy_album_opened', ALBUM_KEY)
    return url
