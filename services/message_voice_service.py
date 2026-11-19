"""Transactional tap-to-speak entitlements; synthesis happens outside this module.

reserve -> synthesize its server-selected text/voice -> finish (or fail).
All mutations acquire the same account lock as trial_caps.take_voice. No remote
calls, disk writes, arbitrary client text, or separate wallet transactions here.
"""
from __future__ import annotations

import re
import struct
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select, update

from config import ADMIN_TELEGRAM_IDS, SPEAK_FREE_PER_DAY, SPEAK_PEACH_COST
from models.app_models import ChatMedia, Message, MessageVoice, ProductEvent, User
from services import trial_caps, voice_humanize
from services.db import SessionLocal

PENDING_TTL = timedelta(minutes=3)  # longer than the caller's 90-second TTS deadline
FREE_EVENT = 'speak_free'
MAX_AUDIO_BYTES = 20 * 1024 * 1024
_CID = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
_THINK = re.compile(r'<(think|thinking|analysis|reasoning)\b[^>]*>.*?(?:</\1\s*>|\Z)', re.I | re.S)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _positive_int(value) -> bool:
    return type(value) is int and value > 0


def _error(name: str, **extra) -> dict:
    return {'ok': False, 'error': name, **extra}


def _ready(row: MessageVoice, *, cached: bool = True) -> dict:
    result = {'ok': True, 'status': 'ready', 'voice_id': row.id, 'url': row.url,
              'charged': 0 if cached else row.bonus_spent + row.bought_spent}
    if cached:
        result['cached'] = True
    return result


def _source_part(telegram_id: int, message: Message, part: int) -> tuple[str, str] | None:
    from services.chat_service import duo_lines, message_block
    from services.chat_guest_service import speakers

    # Historical <think> blocks predate the structured THOUGHT/DRAFT parser.
    visible = message_block(_THINK.sub('', message.content or '')).strip()
    lines = duo_lines(visible)
    speaker_id = message.character_id
    if lines:
        if part >= len(lines):
            return None
        who, visible = lines[part]
        speaker_id = speakers(telegram_id, message.character_id).get(who)
        # Never silently fall back to the host's voice for an unknown guest.
        if not speaker_id or not _CID.fullmatch(speaker_id):
            return None
    elif part != 0:
        return None
    if not voice_humanize.ENABLED:
        visible = ''.join(ch for ch in visible if ch.isalnum() or ch in " .,!?:;-—…()«»'\n")
    visible = visible[:600]
    return (visible, speaker_id) if visible.strip() else None


def _refund(session, row: MessageVoice, now: datetime) -> bool:
    """Only a positive pending guard permits a refund, while holding User's lock."""
    if row.status != 'pending':
        return False
    session.execute(update(User).where(User.id == row.user_id).values(
        bonus_peaches=func.coalesce(User.bonus_peaches, 0) + row.bonus_spent,
        photo_credits=func.coalesce(User.photo_credits, 0) + row.bought_spent),
        execution_options={'synchronize_session': False})
    if row.quota_event_id is not None:
        session.execute(delete(ProductEvent).where(
            ProductEvent.id == row.quota_event_id, ProductEvent.user_id == row.user_id,
            ProductEvent.event_name.in_((FREE_EVENT, trial_caps.VOICE_EVENT))))
    row.status = 'failed'
    row.quota_event_id = None
    row.updated_at = now
    # Keep the exact split as audit data. The failed guard prevents reuse;
    # reserve replaces both fields when it starts a new attempt.
    session.flush()
    return True


def _recover(session, user: User, now: datetime) -> None:
    expired = session.scalars(select(MessageVoice).where(
        MessageVoice.user_id == user.id, MessageVoice.status == 'pending',
        MessageVoice.updated_at < now - PENDING_TTL)).all()
    for row in expired:
        _refund(session, row, now)
    if expired:
        session.refresh(user)  # wallet SQL above deliberately avoids stale ORM writes


def reserve(telegram_id: int, character_id: str, message_id: int, *, part: int = 0,
            allow_paid: bool = False, quoted_price: int | None = None) -> dict:
    if (not _positive_int(telegram_id) or not _positive_int(message_id)
            or not isinstance(character_id, str) or not _CID.fullmatch(character_id)
            or type(part) is not int or part < 0 or type(allow_paid) is not bool):
        return _error('bad_request')
    with SessionLocal.begin() as session:
        user = trial_caps.lock_voice_user(session, telegram_id)
        if user is None:
            return _error('not_found')
        now = _now()
        # Account-wide, even if this request replays a different message or is
        # refused below. Returning inside begin() still commits the recovery.
        _recover(session, user, now)
        source = session.scalar(select(Message).where(
            Message.id == message_id, Message.user_id == user.id,
            Message.character_id == character_id, Message.role == 'assistant'))
        if source is None:
            return _error('not_found')
        row = session.scalar(select(MessageVoice).where(
            MessageVoice.user_id == user.id, MessageVoice.message_id == message_id,
            MessageVoice.part == part))
        if row is not None:
            if row.status == 'ready':
                return _ready(row)
            if row.status == 'pending':
                return _error('voice_pending')
            if row.status != 'failed':
                return _error('bad_request')
        # A message already delivered as audio is an entitlement, not a new TTS.
        if source.media_kind == 'voice' and source.media_url:
            if part != 0:
                return _error('bad_request')
            if row is None:
                row = MessageVoice(user_id=user.id, message_id=message_id, part=0,
                                   character_id=character_id, created_at=now)
                session.add(row)
            row.status, row.attempt = 'ready', str(uuid4())
            row.url, row.updated_at = source.media_url, now
            row.bonus_spent = row.bought_spent = 0
            row.quota_event_id = None
            session.flush()
            return _ready(row)
        selected = _source_part(telegram_id, source, part)
        if selected is None:
            return _error('bad_request')
        text, speaker_id = selected
        quota_event_id = None
        free_left = None
        included = telegram_id in ADMIN_TELEGRAM_IDS
        if not included:
            included, quota_event_id, _plan_left = trial_caps.reserve_voice_uid(
                user.id, session=session, character_id=speaker_id, now=now)
            if included and quota_event_id is None:
                # No active subscription: the existing UTC account/day taste.
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                used = int(session.scalar(select(func.count(ProductEvent.id)).where(
                    ProductEvent.user_id == user.id, ProductEvent.event_name == FREE_EVENT,
                    ProductEvent.created_at >= start,
                    ProductEvent.created_at < start + timedelta(days=1))) or 0)
                free_left = max(0, SPEAK_FREE_PER_DAY - used)
                included = free_left > 0
                if included:
                    event = ProductEvent(user_id=user.id, character_id=speaker_id,
                                         event_name=FREE_EVENT, created_at=now)
                    session.add(event)
                    session.flush()
                    quota_event_id = event.id
                    free_left -= 1
        bonus = bought = 0
        if not included:
            # A race that takes the last free slot never grants paid consent.
            if not allow_paid or type(quoted_price) is not int or quoted_price != SPEAK_PEACH_COST:
                return _error('payment_required', price=SPEAK_PEACH_COST)
            free_left = None  # A paid note is not the last free daily note.
            bonus = min(max(0, user.bonus_peaches or 0), SPEAK_PEACH_COST)
            bought = SPEAK_PEACH_COST - bonus
            charged = session.execute(update(User).where(
                User.id == user.id, func.coalesce(User.bonus_peaches, 0) >= bonus,
                func.coalesce(User.photo_credits, 0) >= bought).values(
                    bonus_peaches=func.coalesce(User.bonus_peaches, 0) - bonus,
                    photo_credits=func.coalesce(User.photo_credits, 0) - bought),
                execution_options={'synchronize_session': False}).rowcount
            if not charged:
                return _error('insufficient_peaches', price=SPEAK_PEACH_COST)
        if row is None:
            row = MessageVoice(user_id=user.id, message_id=message_id, part=part,
                               character_id=speaker_id, created_at=now)
            session.add(row)
        row.status, row.attempt = 'pending', str(uuid4())
        row.character_id = speaker_id
        row.bonus_spent, row.bought_spent = bonus, bought
        row.quota_event_id = quota_event_id
        row.filename = row.url = None
        row.updated_at = now
        session.flush()
        return {'ok': True, 'status': 'pending', 'voice_id': row.id, 'attempt': row.attempt,
                'text': text, 'voice_style': user.voice_style or 'nova',
                'character_id': speaker_id, 'free_left': free_left, 'charged': bonus + bought}


def _audio_format(audio: bytes) -> tuple[str, str] | None:
    """Check complete audio framing, not just a magic prefix or a provider's MIME.

    This is a container/header check, not a remote call or a codec decoder.
    WAV PCM/float, Ogg Opus/Vorbis, and MPEG Layer III are accepted.
    """
    if not isinstance(audio, bytes) or not 32 <= len(audio) <= MAX_AUDIO_BYTES:
        return None
    if audio.startswith(b'RIFF') and audio[8:12] == b'WAVE':
        end = int.from_bytes(audio[4:8], 'little') + 8
        if end != len(audio):
            return None
        pos, alignment, data_size = 12, 0, 0
        while pos + 8 <= end:
            tag = audio[pos:pos + 4]
            size = int.from_bytes(audio[pos + 4:pos + 8], 'little')
            pos += 8
            if pos + size > end:
                return None
            if tag == b'fmt ':
                if size < 16:
                    return None
                codec, channels, rate, byte_rate, alignment, bits = struct.unpack_from('<HHIIHH', audio, pos)
                if (codec not in (1, 3, 0xfffe) or not 1 <= channels <= 8
                        or not 8000 <= rate <= 384000 or bits not in (8, 16, 24, 32, 64)
                        or alignment != channels * bits // 8 or byte_rate != rate * alignment):
                    return None
                if codec == 0xfffe and size < 40:
                    return None
            elif tag == b'data':
                data_size += size
            pos += size + (size % 2)
        if pos == end and alignment and data_size >= alignment and data_size % alignment == 0:
            return 'wav', 'audio/wav'
        return None
    if audio.startswith(b'OggS'):
        pos, packets, packet, last_flags = 0, [], bytearray(), 0
        while pos < len(audio):
            if pos + 27 > len(audio) or audio[pos:pos + 5] != b'OggS\x00':
                return None
            last_flags = audio[pos + 5]
            segments = audio[pos + 26]
            table_end = pos + 27 + segments
            if table_end > len(audio):
                return None
            lengths = audio[pos + 27:table_end]
            payload_end = table_end + sum(lengths)
            if payload_end > len(audio):
                return None
            cursor = table_end
            for size in lengths:
                packet.extend(audio[cursor:cursor + size])
                cursor += size
                if size < 255:
                    # Only the first three headers need retaining.
                    packets.append(bytes(packet[:64]))
                    packet.clear()
            pos = payload_end
        if packet or not last_flags & 4:
            return None
        opus = (len(packets) >= 3 and packets[0].startswith(b'OpusHead')
                and len(packets[0]) >= 19 and packets[0][8] == 1 and packets[0][9] > 0
                and packets[1].startswith(b'OpusTags') and bool(packets[2]))
        vorbis = (len(packets) >= 4 and packets[0].startswith(b'\x01vorbis')
                  and len(packets[0]) >= 30 and packets[1].startswith(b'\x03vorbis')
                  and packets[2].startswith(b'\x05vorbis') and bool(packets[3]))
        return ('ogg', 'audio/ogg') if opus or vorbis else None
    # ID3 alone is metadata, not audio. Require at least two complete MP3 frames.
    pos = 0
    if audio.startswith(b'ID3'):
        if audio[3] not in (2, 3, 4) or any(b & 128 for b in audio[6:10]):
            return None
        size = sum(b << shift for b, shift in zip(audio[6:10], (21, 14, 7, 0)))
        pos = 10 + size + (10 if audio[3] == 4 and audio[5] & 16 else 0)
    frames = 0
    while pos + 4 <= len(audio):
        if len(audio) - pos == 128 and audio[pos:pos + 3] == b'TAG':
            pos += 128
            break
        h = int.from_bytes(audio[pos:pos + 4], 'big')
        version, layer = (h >> 19) & 3, (h >> 17) & 3
        bitrate, sample = (h >> 12) & 15, (h >> 10) & 3
        if (h >> 21 != 0x7ff or version == 1 or layer != 1
                or bitrate in (0, 15) or sample == 3):
            return None
        rates = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
        if version != 3:
            rates = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
        rate = (44100, 48000, 32000)[sample] // (1 if version == 3 else 2 if version == 2 else 4)
        length = (144000 if version == 3 else 72000) * rates[bitrate] // rate + ((h >> 9) & 1)
        if pos + length > len(audio):
            return None
        pos += length
        frames += 1
    return ('mp3', 'audio/mpeg') if frames >= 2 and pos == len(audio) else None


def _current(row, attempt: str) -> bool:
    return row is not None and row.status == 'pending' and row.attempt == attempt


def finish(telegram_id: int, voice_id: int, attempt: str, audio: bytes) -> dict:
    if not _positive_int(telegram_id) or not _positive_int(voice_id) or not isinstance(attempt, str):
        return _error('bad_request')
    audio_format = _audio_format(audio)  # no account transaction during validation
    with SessionLocal.begin() as session:
        user = trial_caps.lock_voice_user(session, telegram_id)
        row = session.scalar(select(MessageVoice).where(
            MessageVoice.id == voice_id, MessageVoice.user_id == user.id)) if user else None
        if not _current(row, attempt):
            return _error('voice_stale')
        now = _now()
        if row.updated_at < now - PENDING_TTL:
            _refund(session, row, now)
            return _error('voice_stale')
        if audio_format is None:
            _refund(session, row, now)
            return _error('invalid_audio')
        ext, content_type = audio_format
        # Same shape as webapp_service's cache names. UUID-sized numeric prefix
        # avoids collisions without changing the established eight-hex suffix.
        token = uuid4()
        filename = f'{token.int}_{token.hex[:8]}.{ext}'
        session.add(ChatMedia(telegram_id=str(telegram_id), filename=filename,
                              content_type=content_type, data=audio, created_at=now))
        row.filename, row.url = filename, f'/webapp/media/{filename}'
        row.status, row.updated_at = 'ready', now
        session.add(ProductEvent(user_id=user.id, character_id=row.character_id,
                                 event_name='speak_message', value=row.bonus_spent + row.bought_spent,
                                 created_at=now))
        session.flush()
        return _ready(row, cached=False)


def fail(telegram_id: int, voice_id: int, attempt: str) -> bool:
    if not _positive_int(telegram_id) or not _positive_int(voice_id) or not isinstance(attempt, str):
        return False
    with SessionLocal.begin() as session:
        user = trial_caps.lock_voice_user(session, telegram_id)
        row = session.scalar(select(MessageVoice).where(
            MessageVoice.id == voice_id, MessageVoice.user_id == user.id)) if user else None
        return _refund(session, row, _now()) if _current(row, attempt) else False


def mark_playback(telegram_id: int, voice_id: int, event: str) -> bool:
    """Record play/end once per owned ready entitlement, without text metadata."""
    if not _positive_int(telegram_id) or not _positive_int(voice_id) or event not in ('play', 'end'):
        return False
    with SessionLocal.begin() as session:
        user = trial_caps.lock_voice_user(session, telegram_id)
        row = session.scalar(select(MessageVoice).where(
            MessageVoice.id == voice_id, MessageVoice.user_id == user.id,
            MessageVoice.status == 'ready')) if user else None
        if row is None:
            return False
        field = 'played_at' if event == 'play' else 'ended_at'
        if getattr(row, field) is not None:
            return False
        now = _now()
        setattr(row, field, now)
        session.add(ProductEvent(user_id=user.id, character_id=row.character_id,
                                 event_name=f'speak_{event}', created_at=now))
        return True


def ready_by_messages(user_id: int, message_ids) -> dict:
    """Internal history helper: keys are Message ids, never Telegram ids."""
    if not _positive_int(user_id):
        return {}
    ids = {mid for mid in message_ids if _positive_int(mid)}
    result = {}
    with SessionLocal() as session:
        # Chunk to stay below SQLite's bind-parameter ceiling for long histories.
        ordered = sorted(ids)
        for offset in range(0, len(ordered), 500):
            rows = session.scalars(select(MessageVoice).join(Message, Message.id == MessageVoice.message_id).where(
                MessageVoice.user_id == user_id, Message.user_id == user_id,
                Message.role == 'assistant', MessageVoice.message_id.in_(ordered[offset:offset + 500]),
                MessageVoice.status == 'ready').order_by(MessageVoice.message_id, MessageVoice.part))
            for row in rows:
                result.setdefault(row.message_id, []).append(
                    {'part': row.part, 'url': row.url, 'voice_id': row.id})
    return result
