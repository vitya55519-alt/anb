"""V3.107.0 — the evening ritual arrives as her voice note.

Owner: «может вечернее сообщение будет голосовое? для русских на русском,
для англ пользователей на английском, всем одно и то же» — every user, free
or Premium, gets the evening line spoken in her own voice (the same TTS chain
as chat voice: Gemini via SpicyAPI → Grok → fallbacks), with the text kept as
the caption. Russian users hear Russian, English users hear English: the
Russian-only evening template is replaced by an English line for them.

Flag: EVENING_VOICE_ENABLED (default on). Any TTS failure → plain text, as before.
"""
from __future__ import annotations

import logging
import os
import random
import re

logger = logging.getLogger(__name__)

ENABLED = os.getenv('EVENING_VOICE_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
CAPTION_LIMIT = 1000

# The Russian template pool lives in retention_features_service; the English
# side had none, so EN users got Russian evenings. Short, warm, one question.
EN_EVENING = (
    "hey you… how was your day? I kept thinking about you tonight",
    "evening 🌙 tell me how your day went, I want to hear everything",
    "I'm finally home and cozy… how are you doing tonight?",
    "it's getting late and I miss you a little. how was your day?",
    "so… did today treat you well? come tell me before bed",
)

_EMOJI = re.compile('[\U0001F000-\U0001FAFF☀-➿️‍]+')


def en_evening_line() -> str:
    return random.choice(EN_EVENING)


# V3.121.0: shared morning ritual needs an English line too.
EN_MORNING = (
    "good morning… I just woke up and you were my first thought",
    "morning 🙂 did you sleep well? I want to hear how your day starts",
    "hey sleepyhead… coffee's ready, how are you this morning?",
    "good morning, you. have a good day, and tell me about it tonight",
)


def en_morning_line() -> str:
    return random.choice(EN_MORNING)


def spoken_text(text: str) -> str:
    """What she says aloud: no emojis, no markup, collapsed spaces."""
    t = _EMOJI.sub(' ', text or '')
    t = re.sub(r'[*_`#>]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def language_matches(text: str, lang: str) -> bool:
    """Never read a Russian line to an English user (or the other way)."""
    try:
        from services.voice_service import detect_voice_language
        got = detect_voice_language(text) or ''
    except Exception:
        return False
    return got.startswith('en') if lang == 'en' else got.startswith('ru')


async def voice_bytes(text: str, character_id: str, lang: str, mood: str = 'evening') -> bytes | None:
    """Her voice for the evening line, or None (then the text goes as before)."""
    if not ENABLED:
        return None
    line = spoken_text(text)
    if not line or not language_matches(line, lang):
        return None
    try:
        from services.voice_service import synthesize_bytes
        audio = await synthesize_bytes(line, None, character_id=character_id, mood=mood)
        return audio or None
    except Exception:
        logger.exception('evening voice synth failed character=%s', character_id)
        return None


def caption(text: str) -> str:
    return text if len(text) <= CAPTION_LIMIT else text[:CAPTION_LIMIT - 1].rstrip() + '…'


# ── V3.110.0: a photo of her comes with the evening voice ───────────────
# Owner: «хотелось чтобы с голосовым каждый вечер приходила фотка» and «бери
# рандомные фотки из генерации» — the plain «photo» entries of the admin feed
# «Генерации пользователей» for THIS girl (same character_id as his chat).
# Budget rule (29.10): no new renders, only photos that already exist.
#  • lingerie/flirty is fine as bait, but only for users who confirmed 18+;
#    full nudity never goes out (the evening reaches free users too);
#  • «undress:»/«animate:» results, «hot»/«cosplay» kinds and failed renders
#    are never candidates; user uploads are not in that feed at all;
#  • «трёхрукие»: each candidate gets one cheap Gemini vision check (cached
#    per photo forever) for broken anatomy and nudity, and the owner can hide
#    any photo with «🚫 Брак» in the feed;
#  • each user gets a photo he has not had in the evening before; when none
#    is left, her ready pool is the fallback.
PHOTO_ENABLED = os.getenv('EVENING_PHOTO_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
PICK_EVENT = 'evening_photo_pick'
QC_EVENT = 'evening_photo_qc'
QC_PER_PICK = max(1, int(os.getenv('EVENING_PHOTO_QC_PER_PICK', '4')))
_NUDE_TEXT = re.compile(
    r'(гол(ая|ую|ой|еньк|ыш)|обнаж|без одежд|разде|топлес|без бель|без трус|без лифчик|сиськ|сос(ок|ки)|киск|'
    r'nude|naked|topless|undress|fully_nude)', re.I)
QC_PROMPT = (
    'Check this AI-generated photo of a woman. Reply with ONE line of JSON only: '
    '{"defect": true|false, "nudity": "none"|"lingerie"|"nude"}. '
    'defect=true if anything is anatomically wrong: extra or missing arms, hands, legs or fingers, '
    'merged or melted body parts, a distorted face, two heads, broken limbs, garbled body. '
    'nudity: "nude" if a nipple, genitals or a bare bottom is visible; "lingerie" for underwear, '
    'swimwear or see-through clothes; otherwise "none".'
)


def candidate_prompt_ok(prompt: str) -> bool:
    """Cheap text pre-filter before the vision check."""
    p = (prompt or '').strip()
    if not p or p.startswith(('❌', 'animate')) or 'http' in p.lower():
        return False
    if p.startswith('undress'):
        # owner: «раздевание сделано нашей моделью» — allowed only when the
        # source is proven to be a bot render of her (checked in _candidates)
        return bool(undress_source(p)) and not _NUDE_TEXT.search(p.replace('undress', ''))
    if ':' in p.split()[0] or '/webapp/media/' in p:
        return False  # hot-menu keys / anything made from an uploaded photo
    return not _NUDE_TEXT.search(p)


_SRC = re.compile(r'^undress:\s*/webapp/media/([A-Za-z0-9_.\-]+)\s*$')


def undress_source(prompt: str) -> str | None:
    m = _SRC.match((prompt or '').strip())
    return m.group(1) if m else None


def parse_qc(text: str) -> dict | None:
    import json
    m = re.search(r'\{.*\}', text or '', re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    nud = str(d.get('nudity', '')).lower()
    if nud not in ('none', 'lingerie', 'nude') or not isinstance(d.get('defect'), bool):
        return None
    return {'defect': d['defect'], 'nudity': nud}


def verdict_allows(v: dict | None, adult: bool) -> bool:
    if not v or v.get('rejected') or v.get('defect'):
        return False
    return v.get('nudity') == 'none' or (v.get('nudity') == 'lingerie' and adult)


def _verdicts(s, ids) -> dict[int, dict]:
    import json
    from sqlalchemy import select
    from models.app_models import ProductEvent
    out: dict[int, dict] = {}
    if not ids:
        return out
    for value, meta in s.execute(select(ProductEvent.value, ProductEvent.metadata_json)
                                 .where(ProductEvent.event_name == QC_EVENT,
                                        ProductEvent.value.in_([float(i) for i in ids]))
                                 .order_by(ProductEvent.id)).all():
        try:
            d = json.loads(meta or '{}')
        except Exception:
            d = {}
        gid = int(value)
        if out.get(gid, {}).get('rejected'):
            continue  # the owner's «брак» always wins
        out[gid] = d
    return out


def save_verdict(gen_id: int, verdict: dict) -> None:
    import json
    from models.app_models import ProductEvent
    from services.db import SessionLocal
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=None, character_id='', event_name=QC_EVENT,
                           value=float(gen_id), metadata_json=json.dumps(verdict)))
        s.commit()


def reject_generation(gen_id: int) -> None:
    """Owner's «🚫 Брак»: this photo never goes out in the evening again."""
    save_verdict(int(gen_id), {'rejected': True})


async def vision_check(data: bytes, mime: str) -> dict | None:
    import base64
    b64 = base64.b64encode(data).decode()
    if len(b64) > 3_000_000:
        return None
    try:
        from services.llm_provider_service import generate_text
        r = await generate_text([{'role': 'user', 'content': [
            {'type': 'text', 'text': QC_PROMPT},
            {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{b64}'}},
        ]}], max_tokens=60, temperature=0.0, purpose='evening_photo_qc')
    except Exception as exc:
        logger.warning('evening photo qc failed: %s: %s', type(exc).__name__, exc)
        return None
    return parse_qc(r.text)


def _candidates(character_id: str, uid: int | None):
    """[(gen_id, filename, verdict|None)] — fresh clean-prompt photos of her."""
    import random
    from sqlalchemy import select
    from models.app_models import ProductEvent, UserGeneration
    from services.db import SessionLocal
    with SessionLocal() as s:
        rows = s.execute(
            select(UserGeneration.id, UserGeneration.filename, UserGeneration.prompt)
            .where(UserGeneration.kind == 'photo', UserGeneration.character_id == character_id,
                   UserGeneration.filename.is_not(None),
                   (UserGeneration.engine.is_(None)) | (UserGeneration.engine != 'error'))
            .order_by(UserGeneration.id.desc()).limit(500)
        ).all()
        seen = set()
        if uid:
            seen = {int(v) for (v,) in s.execute(
                select(ProductEvent.value).where(ProductEvent.user_id == uid,
                                                 ProductEvent.event_name == PICK_EVENT)).all() if v}
        fresh = [r for r in rows if r.id not in seen and candidate_prompt_ok(r.prompt)]
        # an «undress» stays only if its source file is itself a bot render of
        # HER from text (not an upload, not another photo action)
        srcs = {undress_source(r.prompt) for r in fresh if undress_source(r.prompt)}
        good_src = set()
        if srcs:
            for fn, pr in s.execute(select(UserGeneration.filename, UserGeneration.prompt)
                                    .where(UserGeneration.filename.in_(srcs),
                                           UserGeneration.character_id == character_id,
                                           UserGeneration.kind.in_(('photo', 'hot', 'cosplay')),
                                           (UserGeneration.engine.is_(None)) | (UserGeneration.engine != 'error'))).all():
                if '/webapp/media/' not in (pr or '') and not (pr or '').startswith(('undress', 'animate')):
                    good_src.add(fn)
        fresh = [r for r in fresh if not undress_source(r.prompt) or undress_source(r.prompt) in good_src]
        verdicts = _verdicts(s, [r.id for r in fresh])
    random.shuffle(fresh)
    return [(r.id, r.filename, verdicts.get(r.id)) for r in fresh]


def _media(filename: str):
    from sqlalchemy import select
    from models.app_models import ChatMedia
    from services.db import SessionLocal
    with SessionLocal() as s:
        m = s.execute(select(ChatMedia.data, ChatMedia.content_type)
                      .where(ChatMedia.filename == filename).limit(1)).first()
    ctype = (m.content_type or '') if m else ''
    return (m.data, ctype) if m and m.data and ctype.startswith('image/') else None


def _record_pick(uid: int, character_id: str, gen_id: int, filename: str) -> None:
    import json
    from models.app_models import ProductEvent
    from services.db import SessionLocal
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=uid, character_id=character_id, event_name=PICK_EVENT,
                           value=float(gen_id), metadata_json=json.dumps({'file': filename})))
        s.commit()


async def evening_photo(character_id: str, uid: int | None, adult: bool = False) -> tuple[bytes, str, str] | None:
    """(bytes, content_type, 'photo') of a ready photo of her, or None. $0 renders."""
    import asyncio
    if not PHOTO_ENABLED or not character_id:
        return None
    try:
        cands = await asyncio.to_thread(_candidates, character_id, uid)
        checks = 0
        # already-approved photos first, then unchecked ones (a few per pick)
        cands.sort(key=lambda c: 0 if c[2] else 1)
        for gen_id, filename, verdict in cands:
            if verdict is not None and not verdict_allows(verdict, adult):
                continue
            media = await asyncio.to_thread(_media, filename)
            if not media:
                continue
            if verdict is None:
                if checks >= QC_PER_PICK:
                    continue
                checks += 1
                verdict = await vision_check(*media)
                if verdict is None:
                    continue  # no verdict, no send; checked again next time
                await asyncio.to_thread(save_verdict, gen_id, verdict)
                if not verdict_allows(verdict, adult):
                    continue
            if uid:
                await asyncio.to_thread(_record_pick, uid, character_id, gen_id, filename)
            return media[0], media[1], 'photo'
    except Exception:
        logger.exception('evening photo (user generations) failed character=%s', character_id)
    try:
        from services.retention_features_service import random_proactive_photo
        picked = await asyncio.to_thread(random_proactive_photo, character_id, uid)
        if picked and picked[2] == 'photo' and picked[0]:
            return picked[0], picked[1] or 'image/jpeg', 'photo'
    except Exception:
        logger.exception('evening photo (pool) failed character=%s', character_id)
    return None


# ── V3.150.0: the owner pins the photo that goes under the voice note ─────
# Owner: «дай мне возможность выбирать фото под голосовое». The automatic pick
# above is a roulette he only sees once the bubble is already on his screen. In
# test mode he now flips through her ready frames and pins one for today's
# morning/evening ritual of THIS girl — one ProductEvent row, so a redeploy
# keeps it and the next day the rotation takes over again. «🔄 Авто» releases it.
CHOICE_EVENT = 'ritual_photo_pick'
CANDIDATE_LIMIT = 24


def _gen_candidates(character_id: str) -> list[dict]:
    """Her ready bot renders, clean ones only: the owner's «🚫 Брак» and any
    nudity never reach the list, an unchecked frame is offered with a warning."""
    out = []
    for gen_id, _filename, verdict in _candidates(character_id, None)[:CANDIDATE_LIMIT]:
        if verdict and not verdict_allows(verdict, False):
            continue
        out.append({'source': 'gen', 'ref': int(gen_id), 'checked': verdict is not None})
    return out


def _pool_candidates(character_id: str) -> list[dict]:
    from sqlalchemy import select
    from models.app_models import ProactivePhoto
    from services.db import SessionLocal
    from services.retention_features_service import proactive_photo_retired
    with SessionLocal() as s:
        rows = s.execute(
            select(ProactivePhoto.id, ProactivePhoto.kind, ProactivePhoto.created_at)
            .where(ProactivePhoto.character_id == character_id, ProactivePhoto.kind == 'photo')
            .order_by(ProactivePhoto.id.desc()).limit(CANDIDATE_LIMIT)
        ).all()
    return [{'source': 'pool', 'ref': int(r.id), 'checked': True}
            for r in rows if not proactive_photo_retired(r.kind, r.created_at)]


def owner_candidates(character_id: str) -> list[dict]:
    """[{source, ref, checked}] — her generations first, then his own pool."""
    out: list[dict] = []
    try:
        out += _gen_candidates(character_id)
    except Exception:
        logger.exception('ritual photo candidates (generations) failed character=%s', character_id)
    try:
        out += _pool_candidates(character_id)
    except Exception:
        logger.exception('ritual photo candidates (pool) failed character=%s', character_id)
    return out[:CANDIDATE_LIMIT]


def candidate_media(source: str, ref: int):
    """(bytes, content_type, kind) of one candidate, or None when the file is
    gone — an ephemeral render that never made it into ChatMedia."""
    from sqlalchemy import select
    from models.app_models import ProactivePhoto, UserGeneration
    from services.db import SessionLocal
    try:
        with SessionLocal() as s:
            if source == 'pool':
                row = s.get(ProactivePhoto, int(ref))
                if not row or not row.image_bytes:
                    return None
                return row.image_bytes, (row.content_type or 'image/jpeg'), (row.kind or 'photo')
            filename = s.scalar(select(UserGeneration.filename).where(UserGeneration.id == int(ref)))
    except Exception:
        logger.exception('ritual photo candidate failed source=%s ref=%s', source, ref)
        return None
    return _media(filename) if filename else None


def set_choice(kind: str, day: str, character_id: str, source: str | None, ref: int | None) -> None:
    """Pin a frame for today's ritual — or release it back to the rotation."""
    import json
    from models.app_models import ProductEvent
    from services.db import SessionLocal
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=None, character_id=character_id or '', event_name=CHOICE_EVENT,
                           value=float(ref or 0),
                           metadata_json=json.dumps({'kind': kind, 'day': day,
                                                     'source': source, 'ref': ref})))
        s.commit()


def get_choice(kind: str, day: str, character_id: str) -> dict | None:
    """The newest pinned frame for this girl and day, None when auto."""
    import json
    from sqlalchemy import select
    from models.app_models import ProductEvent
    from services.db import SessionLocal
    try:
        with SessionLocal() as s:
            rows = s.execute(
                select(ProductEvent.metadata_json)
                .where(ProductEvent.event_name == CHOICE_EVENT,
                       ProductEvent.character_id == (character_id or ''))
                .order_by(ProductEvent.id.desc()).limit(20)
            ).all()
        for (meta,) in rows:
            try:
                d = json.loads(meta or '{}')
            except Exception:
                continue
            if d.get('kind') != kind or d.get('day') != day:
                continue
            return d if d.get('source') else None
    except Exception:
        logger.exception('ritual photo choice read failed character=%s', character_id)
    return None


async def chosen_photo(kind: str, day: str, character_id: str):
    """The owner's pinned frame for this ritual, or None → pick automatically."""
    import asyncio
    if not character_id:
        return None
    choice = await asyncio.to_thread(get_choice, kind, day, character_id)
    if not choice:
        return None
    media = await asyncio.to_thread(candidate_media, str(choice.get('source')), choice.get('ref'))
    if not media or not media[0]:
        return None
    return media


# ── V3.108.0: owner's one-off voice cast to everyone ─────────────────────
# «всем одно и то же»: one line per language, voiced once per girl and
# reused for every user of that girl (a handful of TTS calls, not hundreds).
CAST_LINES = {
    'ru': 'привет… я уже лежу и думаю о тебе. как прошёл твой день? расскажешь мне? я жду',
    'en': "hey you… I'm already in bed and thinking about you. how was your day? tell me, I'm waiting",
}
CAST_ACTIVE_DAYS = max(1, int(os.getenv('VOICE_CAST_ACTIVE_DAYS', '30')))


def cast_recipients(days: int = CAST_ACTIVE_DAYS) -> list[tuple[int, int, str, str]]:
    """(user_id, telegram_id, character_id, lang) for everyone who kept her
    messages on and was here in the last ``days`` days."""
    import datetime as dt
    from sqlalchemy import select
    from models.app_models import User
    from services.db import SessionLocal
    cutoff = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=days)
    with SessionLocal() as s:
        rows = s.execute(select(User.id, User.telegram_id, User.selected_character, User.ui_lang)
                         .where(User.proactive_enabled == True, User.last_active_at >= cutoff)).all()  # noqa: E712
    out = []
    for uid, tid, char, lang in rows:
        try:
            tg = int(tid)
        except (TypeError, ValueError):
            continue
        out.append((int(uid), tg, char or '', 'en' if (lang or '').lower().startswith('en') else 'ru'))
    return out
