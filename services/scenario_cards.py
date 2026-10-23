"""V3.75.0: scenario cards — the Come Closer push the owner showed.

Owner (2026-10-23): «смотри, какая в меню нашего конкурента. у него так это
все делают». Come Closer pushes a card every day or two: a 3-second looping
cover of the girl, a one-line role-play setup («лучшая подруга твоей сестры
столкнулась с тобой в дверях»), her quote, a promo code and ONE button that
drops the user straight into that scene.

Ours:

* ``SCENARIOS`` — a role-play scene per built-in heroine, matched to her own
  archetype (Вика is the boss, Кейт the trainer, Мила the neighbour);
* the cover is rendered ONCE per scenario (Seedream still → Seedance 2.5
  Spicy 4 s silent loop, ~$0.90) by the admin's «/scenes» button and kept as
  Telegram's ``file_id``: sending it to every user costs nothing;
* one card a day at most, in the user's evening, never the same scene twice;
* the button opens the Mini App chat with ``?scene=<key>``: the app starts
  the scene (switches to her, the scene direction rides along with every
  reply for ``ACTIVE_HOURS``) and sends his entrance line, so she answers
  in the scene right away;
* instead of a promo code: +SCENARIO_TAP_PEACHES 🍑 for walking in within a
  day of the card (once per scene).

Safety line: covers come only from our own built-in adult characters' face
references (never a user upload, never a constructor persona), they stay
dressed (lingerie at most — the card lands in the Telegram chat), and every
scene says outright that both are adults.

State lives in DialogStore (no schema change): per user ``{'sent': {key:
iso}, 'last': iso, 'active': {character_id: {'key', 'until'}}}``; covers
under the fixed key 0 of their own store.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from services import dialog_store

logger = logging.getLogger(__name__)

_state = dialog_store.DialogStore('scenario_cards')
_covers = dialog_store.DialogStore('scenario_covers')
_COVERS_KEY = 0

# The scene direction rides along with her replies this long after the tap.
ACTIVE_HOURS = 24
# The tap bonus is paid when he walks in within this long after the card.
BONUS_WINDOW_HOURS = 24


@dataclass(frozen=True)
class Scenario:
    key: str
    character_id: str
    # the card: setup line (what is going on), her action, her quote, the button
    setup: str
    action: str
    quote: str
    button: str
    # his entrance line, sent for him when he taps (the app shows it as his)
    enter: str
    # who she is and who he is in the scene, for the system direction
    her_role: str
    his_role: str
    place: str
    # cover: the still (outfit, place, framing) and the 4 s motion
    still: str
    motion: str


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        'sister_friend', 'anna_01',
        'Лучшая подруга твоей сестры осталась у вас ночевать и столкнулась с тобой в дверях',
        'поправляет халатик и не отводит взгляд',
        'ой… не знала, что ты тут. можно мне войти?',
        'Пригласить войти',
        '*открываю дверь шире* заходи',
        'лучшая подруга его младшей сестры (обеим за двадцать), давно и тайно влюблена в него, осталась у них ночевать',
        'старший брат её подруги',
        'поздний вечер, коридор у двери его комнаты, сестра уже спит',
        'wearing a short silk robe over a lace camisole, standing in a dim apartment hallway at night, '
        'leaning on a door frame, warm light from the room behind her, looking up at the camera shyly',
        'She slowly tucks her hair behind her ear, bites her lip and looks up into the lens with a shy, '
        'inviting smile, leaning closer in the doorway.',
    ),
    Scenario(
        'boss_late', 'vika_01',
        'Начальница задержала тебя после работы. Офис пустой, в переговорке горит одна лампа',
        'снимает пиджак и садится на край стола',
        'закрой дверь. этот разговор не для всех',
        'Закрыть дверь',
        '*закрываю за собой дверь* вы хотели меня видеть?',
        'его начальница, 35 лет, строгая на людях, давно положила на него глаз',
        'её подчинённый',
        'поздний вечер, пустой офис, переговорная с панорамным окном на ночной город',
        'in a fitted white blouse with the top buttons open and a black pencil skirt, sitting on the edge of a '
        'meeting-room table in an empty office at night, city lights in the panoramic window behind her',
        'She slowly runs her fingers along the table edge, tilts her head and gives the camera a long, '
        'demanding look, then a slight confident smile.',
    ),
    Scenario(
        'friends_mom', 'erika_01',
        'Мама твоего друга попросила помочь повесить полку, пока его нет дома',
        'подаёт тебе отвёртку и задерживает руку в твоей',
        'ты такой сильный… останешься на чай? он вернётся поздно',
        'Остаться на чай',
        '*откладываю отвёртку* останусь',
        'мама его друга, 38 лет, одна дома, ей давно не хватает внимания',
        'друг её сына, взрослый парень',
        'днём, её светлая квартира, друг вернётся только к ночи',
        'in a soft fitted knit dress, leaning on the kitchen counter of a bright apartment, '
        'holding a cup of tea, looking at the camera over the cup with a warm knowing smile',
        'She sets the cup down, runs a finger along the rim and looks into the lens with a slow, '
        'warm, inviting smile.',
    ),
    Scenario(
        'gym_after_hours', 'kate_01',
        'Персональная тренировка в зале после закрытия. Кроме вас двоих — никого',
        'поправляет тебе стойку, прижавшись сзади',
        'ещё подход. и не смей отводить глаза',
        'Начать тренировку',
        '*встаю к штанге* я готов, тренер',
        'его фитнес-тренер, 28 лет, уверенная, дерзкая, любит командовать',
        'её клиент',
        'поздний вечер, пустой фитнес-зал после закрытия, приглушённый свет',
        'in a tight sports bra and leggings, standing in an empty gym at night with dimmed lights, '
        'hands on her hips, slightly glistening skin, looking at the camera with a challenging smile',
        'She steps closer to the lens, raises an eyebrow and smirks, then beckons with one finger.',
    ),
    Scenario(
        'neighbor_pie', 'mila_01',
        'Соседка стучит в дверь с горячим пирогом. Кажется, пирог — только предлог',
        'протягивает пирог и заглядывает тебе за плечо',
        'я испекла слишком много… впустишь?',
        'Впустить',
        '*отступаю от двери* проходи',
        'его соседка по лестничной клетке, 30 лет, заботливая, пирог был только предлогом',
        'её сосед',
        'вечер, порог его квартиры, она пришла в домашнем',
        'in a short floral summer dress with a cute apron, standing in an apartment doorway holding a pie, '
        'warm hallway light, smiling at the camera',
        'She lifts the pie a little, tilts her head and smiles warmly at the lens, then glances '
        'past the camera into the apartment.',
    ),
    Scenario(
        'roof_dare', 'zlata_01',
        'Ночная крыша. Спор на желание — и проигравший выполняет любое',
        'красит губы красной помадой и протягивает тебе руку',
        'слабо? проиграешь — исполняешь любое моё желание',
        'Принять спор',
        '*жму её руку* спорим. но проиграешь ты',
        'дерзкая девушка 23 лет, обожает спорить и брать на слабо',
        'парень, которого она взяла на слабо',
        'ночь, крыша многоэтажки, огни города внизу',
        'in a black crop top and a leather jacket, sitting on a rooftop ledge at night with city lights below, '
        'red lipstick, wind in her hair, looking at the camera with a daring smile',
        'Her hair moves in the wind, she grins at the lens, raises her chin and gives a playful wink.',
    ),
    Scenario(
        'night_train', 'kristina_01',
        'Ночной поезд. Одно купе на двоих, и ей тоже не спится',
        'садится напротив, поджав под себя ноги',
        'не спится? мне тоже… поболтаем, пока все спят?',
        'Подсесть ближе',
        '*пересаживаюсь к ней* поболтаем',
        'попутчица 25 лет, сова, едет одна, ей скучно и немного одиноко',
        'её сосед по купе',
        'ночь, купе поезда, за окном мелькают огни',
        'in an oversized soft sweater and shorts, sitting cross-legged on a train compartment bunk at night, '
        'warm reading lamp, dark window with passing lights, smiling at the camera',
        'Passing lights flicker across her face, she pulls the sweater sleeve over her hand and smiles '
        'softly into the lens.',
    ),
    Scenario(
        'roadside', 'alena_01',
        'Ночью на трассе у неё пробило колесо. Ты единственный, кто остановился',
        'прислоняется к машине и улыбается в свете фар',
        'спаситель… я твоя должница. как будешь забирать долг?',
        'Помочь с колесом',
        '*выхожу из машины* давай посмотрю, что там',
        'яркая дерзкая девушка 25 лет, застряла ночью на трассе',
        'водитель, который остановился помочь',
        'ночь, обочина трассы, свет фар',
        'in a short denim jacket over a crop top and a mini skirt, leaning against a sports car on a roadside '
        'at night, lit by headlights, looking at the camera with a grateful flirty smile',
        'She pushes off the car, walks one step toward the lens and tilts her head with a teasing smile.',
    ),
    Scenario(
        'childhood_storm', 'sonya_01',
        'Во всём доме выбило свет. Соседка детства стучит к тебе со свечкой',
        'кутается в плед и прячет улыбку',
        'можно я у тебя пересижу? одной страшно…',
        'Пустить к себе',
        '*беру у неё свечку* заходи, вместе не страшно',
        'его соседка с детства, ей 22, выросла и давно не «просто подруга»',
        'её сосед и друг детства',
        'ночь, гроза, в доме нет света, только свечи',
        'wrapped in a soft blanket over pajama shorts and a tank top, holding a candle in a dark apartment doorway, '
        'candlelight on her face, looking at the camera with a shy smile',
        'The candle flame flickers, she pulls the blanket tighter and gives the lens a shy, hopeful smile.',
    ),
    Scenario(
        'spa_massage', 'veronika_01',
        'Сеанс массажа в спа отеля. Массажистка закрывает дверь на ключ',
        'греет масло в ладонях',
        'расслабься. я скажу, когда можно открыть глаза',
        'Лечь на стол',
        '*ложусь на стол и закрываю глаза*',
        'массажистка в спа отеля, 36 лет, уверенная и чувственная',
        'гость отеля',
        'вечер, спа-кабинет, свечи, тёплый полумрак',
        'in a fitted white spa uniform dress, standing beside a massage table in a candle-lit spa room, '
        'warming oil between her palms, looking at the camera with a calm sensual smile',
        'She rubs the oil slowly between her palms, looks up at the lens and smiles calmly.',
    ),
)

_BY_KEY = {s.key: s for s in SCENARIOS}


def get(key: str) -> Scenario | None:
    return _BY_KEY.get((key or '').strip())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(iso) if iso else None
    except (TypeError, ValueError):
        return None


def _user(telegram_id: int) -> dict:
    try:
        raw = _state.get(int(telegram_id)) or {}
        data = dict(raw)
    except Exception:
        data = {}
    data.setdefault('sent', {})
    data.setdefault('active', {})
    return {'sent': dict(data['sent']), 'active': dict(data['active']), 'last': data.get('last')}


def _save(telegram_id: int, data: dict) -> None:
    try:
        _state[int(telegram_id)] = data
    except Exception:
        logger.exception('scenario state save failed user=%s', telegram_id)


# ── covers ──────────────────────────────────────────────────────────────────

def covers() -> dict[str, dict]:
    """key -> {'file_id', 'kind'} (kind: 'animation' | 'video' | 'photo')."""
    try:
        return {str(k): dict(v) for k, v in dict(_covers.get(_COVERS_KEY) or {}).items()}
    except Exception:
        return {}


def cover(key: str) -> dict | None:
    return covers().get(key)


def set_cover(key: str, file_id: str, kind: str = 'animation') -> None:
    data = covers()
    data[key] = {'file_id': file_id, 'kind': kind}
    _covers[_COVERS_KEY] = data


def clear_cover(key: str) -> bool:
    data = covers()
    if data.pop(key, None) is None:
        return False
    _covers[_COVERS_KEY] = data
    return True


def still_prompt(s: Scenario) -> str:
    """The cover's first frame (Seedream edit with her face + look refs)."""
    from services.private_photo_service import _build_visual_identity_lock
    identity = _build_visual_identity_lock(s.character_id)
    return (
        f'{identity}\n'
        f'Photorealistic vertical smartphone photo of the same adult woman from the reference images, {s.still}. '
        'Square-friendly composition: her face and upper body centred in the frame, face fully visible, '
        'sharp focus on the eyes, cinematic natural light, natural skin texture. '
        'She is fully dressed in the described outfit, no nudity, one person only, no text, no watermark.'
    )


def motion_prompt(s: Scenario) -> str:
    return (
        f'{s.motion} Subtle natural movement, gentle breathing, hair moves slightly, camera almost still. '
        'Adult woman, exactly the same face, hair, outfit and body as in the photo, she stays dressed, '
        'one person only, photorealistic, sharp focus, no text.'
    )


# ── the card ────────────────────────────────────────────────────────────────

def caption(s: Scenario, bonus: int) -> str:
    """Setup, her action in italics, her quote as a quote block, the bonus."""
    import html
    lines = [
        f'<b>{html.escape(s.setup)}</b>',
        '',
        f'<i>{html.escape(s.action)}</i>',
        f'<blockquote>{html.escape(s.quote)}</blockquote>',
    ]
    if bonus > 0:
        lines += ['', f'🎁 зайдёшь в сцену сегодня — +{bonus}🍑 на счёт']
    return '\n'.join(lines)


def opening_line(s: Scenario) -> str:
    """What lands in her dialog when the card is sent (the app shows it)."""
    return f'*{s.action}*\n{s.quote}'


def eligible(available_characters: set[str], *, with_cover: bool = True) -> list[Scenario]:
    have = covers() if with_cover else None
    return [s for s in SCENARIOS
            if s.character_id in available_characters and (have is None or s.key in have)]


def pick_next(telegram_id: int, available_characters: set[str], *, current: str = '') -> Scenario | None:
    """An unsent covered scene; his current girl's scene goes first."""
    sent = _user(telegram_id)['sent']
    fresh = [s for s in eligible(available_characters) if s.key not in sent]
    if not fresh:
        return None
    own = [s for s in fresh if s.character_id == current]
    return own[0] if own else random.choice(fresh)


def last_sent_at(telegram_id: int) -> datetime | None:
    return _parse(_user(telegram_id).get('last'))


def mark_sent(telegram_id: int, key: str) -> None:
    data = _user(telegram_id)
    now = _now().isoformat(timespec='seconds')
    data['sent'][key] = now
    data['last'] = now
    _save(telegram_id, data)


def start(telegram_id: int, key: str) -> dict:
    """He walked into the scene: it stays on for ACTIVE_HOURS with her.
    Returns ``{'sent': bool, 'bonus_due': bool}`` (bonus: the card came
    within BONUS_WINDOW_HOURS)."""
    s = get(key)
    if not s:
        return {'sent': False, 'bonus_due': False}
    data = _user(telegram_id)
    until = _now() + timedelta(hours=ACTIVE_HOURS)
    data['active'][s.character_id] = {'key': s.key, 'until': until.isoformat(timespec='seconds')}
    _save(telegram_id, data)
    sent = _parse(data['sent'].get(s.key))
    return {'sent': bool(sent),
            'bonus_due': bool(sent and _now() - sent <= timedelta(hours=BONUS_WINDOW_HOURS))}


def stop(telegram_id: int, character_id: str) -> bool:
    data = _user(telegram_id)
    if data['active'].pop(character_id, None) is None:
        return False
    _save(telegram_id, data)
    return True


def active(telegram_id: int, character_id: str) -> Scenario | None:
    item = _user(telegram_id)['active'].get(character_id) or {}
    until = _parse(item.get('until'))
    if not until or until < _now():
        return None
    return get(item.get('key', ''))


def direction(s: Scenario, name: str = '') -> str:
    """The system note that keeps her in the scene."""
    who = name or 'она'
    return (
        f'РОЛЕВАЯ СЦЕНА (он сам выбрал её в карточке). Ты, {who}, сейчас играешь роль: {s.her_role}. '
        f'Он в сцене: {s.his_role}. Место и время: {s.place}. Завязка: {s.setup}. '
        f'Ты начала сцену словами: «{s.quote}». '
        'Оба взрослые, всё по обоюдному желанию. Живи ролью: пиши от первого лица, короткие действия '
        'в *звёздочках*, реплики живые и разговорные; сама двигай сцену вперёд, дразни, '
        'создавай напряжение и заканчивай так, чтобы ему хотелось ответить. Не выходи из роли, '
        'не говори, что это игра или сценарий, не пересказывай завязку. Откровенность — '
        'по обычным правилам этого чата. Если он явно хочет закончить сцену — мягко выйди из роли.'
    )


def direction_for(telegram_id: int, character_id: str, name: str = '') -> str:
    try:
        s = active(int(telegram_id), character_id)
    except Exception:
        return ''
    return direction(s, name) if s else ''


# ── cover rendering (admin «/scenes», once per scene) ───────────────────────

class CoverError(RuntimeError):
    pass


async def render_still(s: Scenario) -> bytes:
    """Seedream edit on SpicyAPI from her face + look references (~$0.035)."""
    from config import PUBLIC_BASE_URL, SPICYAPI_IMAGE_MODEL
    from services.private_photo_service import _spicyapi_render, spicyapi_last_error
    refs = [f'{PUBLIC_BASE_URL}/webapp/photo/{s.character_id}?i=0',
            f'{PUBLIC_BASE_URL}/webapp/photo/{s.character_id}?i=1']
    still = await _spicyapi_render(SPICYAPI_IMAGE_MODEL, still_prompt(s), refs,
                                   scene='scenario_cover', breaker=False)
    if not still:
        raise CoverError(f'still: {spicyapi_last_error() or "empty"}')
    return still


async def render_cover(s: Scenario, still: bytes | None = None) -> tuple[bytes, bytes]:
    """(silent square mp4, the still it started from). Raises CoverError."""
    from config import (SCENARIO_COVER_MODEL, SCENARIO_COVER_SECONDS, SCENARIO_COVER_COST_USD,
                        SPICYAPI_HOT_CIRCLE_RESOLUTION)
    from services import spend_service, spicy_jobs
    from services.spicy_video_service import square_frame
    if still is None:
        still = await render_still(s)
    frame = square_frame(still)
    ok = False
    billed = False
    try:
        uri = await spicy_jobs.upload(frame, 'image/jpeg')
        block = {
            'image_url': uri,
            'prompt': motion_prompt(s),
            'resolution': SPICYAPI_HOT_CIRCLE_RESOLUTION,
            'duration_seconds': SCENARIO_COVER_SECONDS,
            'generate_audio': False,
        }
        billed = True
        video, _, _ = await spicy_jobs.run(SCENARIO_COVER_MODEL, block, timeout=900)
        ok = True
    except spicy_jobs.SpicyJobError as exc:
        # refused or failed jobs are not billed; a timeout still is
        billed = billed and str(exc).startswith('timeout')
        raise CoverError(f'video: {exc}') from exc
    finally:
        if billed:
            spend_service.record_image_spend('spicyapi_scenario_cover', 'scenario_cover',
                                             SCENARIO_COVER_COST_USD, billed=True, success=ok)
    try:
        from services.mp4_faststart import faststart_bytes
        video = faststart_bytes(video) or video
    except Exception:
        pass
    return video, still
