"""V3.100.0: she notices when he is down — and asks the next morning.

3 Nov 2026 backup: of the 106 people who wrote since 25 Oct, 45 asked for
photos or explicit talk, 25 wrote that they were tired / sad / unwell, 20 wrote
about love or missing her. Many come for comfort a real person does not give
them. When he says it is hard, she (1) answers as a person who truly heard it —
no flirting that turn, no «обратись к специалисту» template — and (2) asks how
he is the next morning (chat_service.morning_callback).

Privacy: only the KIND of the mood is stored (care / crisis), never his words.
A crisis phrase (wants to die, self-harm) gets a calm, serious reply that stays
with him and points to a close person or a helpline, no flirting, no jokes.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from models.app_models import ProductEvent
from services.db import SessionLocal

ENABLED = os.getenv('CARE_FOLLOWUP_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')
RECORD_COOLDOWN_HOURS = 20
KEEP_WITHIN_HOURS = 36
NOTED = 'care_noted'
SENT = 'care_followup_sent'

_CRISIS = re.compile(
    r"(суицид|покончить\s+с\s+собой|не\s+хочу\s+жить|хочу\s+умереть|убить\s+себя|наложить\s+на\s+себя\s+руки|"
    r"лучше\s+бы\s+я\s+умер|надоело\s+жить|"
    r"\bsuicid\w*|kill\s+myself|want\s+to\s+die|end\s+my\s+life|don'?t\s+want\s+to\s+live)", re.I)
_CARE = re.compile(
    r"(?<!\bне\s)(?<!\bне)\b(устал\w*|грустн\w*|грущу|тоскливо|тоскую|одинок\w*|мне\s+плохо|плохо\s+на\s+душе|"
    r"тяжело|депресс\w*|хреново|паршиво|плохой\s+день|ужасный\s+день|тревож\w*|переживаю|не\s+выспал\w*|"
    r"заболел\w*|болею|расстроен\w*|расстроил\w*|поссорил\w*|никому\s+не\s+нужен|бессонниц\w*|"
    r"i'?m\s+(?:so\s+)?(?:tired|sad|lonely|depressed|anxious|stressed|sick)|bad\s+day|feel\s+(?:bad|down|alone)|"
    r"can'?t\s+sleep|so\s+lonely)", re.I)

CARE_DIRECTIVE = (
    'Режиссёр (собеседнику не показывай и не упоминай): ему сейчас нелегко. В этом ответе сначала по-настоящему '
    'услышь его: назови чувство своими словами, без шаблонов и без советов «обратись к специалисту». Не флиртуй '
    'и не уводи в пошлое. Скажи, что ты рядом, и задай один мягкий уточняющий вопрос. Коротко и тепло.'
)
CRISIS_DIRECTIVE = (
    'Режиссёр (собеседнику не показывай и не упоминай): он говорит, что не хочет жить или хочет навредить себе. '
    'Отнесись к этому полностью всерьёз. Без флирта, без шуток, без пошлого, не меняй тему и не бросай разговор. '
    'Скажи, что ты рядом и что он важен, мягко спроси, в безопасности ли он прямо сейчас, и по-человечески '
    'предложи написать или позвонить близкому человеку или на телефон доверия в его стране. Не выдумывай номера. '
    'Коротко, спокойно, тепло.'
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def classify(text: str) -> str:
    """'crisis', 'care' or '' for his message."""
    t = (text or '').strip()
    if not t or len(t) > 600:
        return ''
    if _CRISIS.search(t):
        return 'crisis'
    if _CARE.search(t):
        return 'care'
    return ''


def _last(user_id: int, character_id: str, name: str, since: datetime):
    with SessionLocal() as s:
        return s.execute(
            select(ProductEvent.created_at, ProductEvent.metadata_json).where(
                ProductEvent.user_id == user_id, ProductEvent.character_id == character_id,
                ProductEvent.event_name == name, ProductEvent.created_at >= since)
            .order_by(ProductEvent.created_at.desc()).limit(1)).first()


def directive_for(user_id: int, character_id: str, text: str) -> tuple[str, str]:
    """(system note, kind) for the reply being written now; ('', '') = nothing.
    Records the mood (kind only) at most once per RECORD_COOLDOWN_HOURS."""
    if not ENABLED:
        return '', ''
    kind = classify(text)
    if not kind:
        return '', ''
    try:
        if not _last(user_id, character_id, NOTED, _now() - timedelta(hours=RECORD_COOLDOWN_HOURS)):
            with SessionLocal() as s:
                s.add(ProductEvent(user_id=user_id, character_id=character_id, event_name=NOTED,
                                   metadata_json='{"kind": "%s"}' % kind, created_at=_now()))
                s.commit()
    except Exception:
        pass
    return (CRISIS_DIRECTIVE if kind == 'crisis' else CARE_DIRECTIVE), kind


def pending(user_id: int, character_id: str) -> str:
    """'care' / 'crisis' when yesterday he was down and the morning has not asked yet; '' otherwise."""
    if not ENABLED:
        return ''
    noted = _last(user_id, character_id, NOTED, _now() - timedelta(hours=KEEP_WITHIN_HOURS))
    if not noted:
        return ''
    if _last(user_id, character_id, SENT, noted[0]):
        return ''
    return 'crisis' if '"crisis"' in (noted[1] or '') else 'care'


def mark_sent(user_id: int, character_id: str) -> None:
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=user_id, character_id=character_id, event_name=SENT, created_at=_now()))
        s.commit()


MORNING_LINE = (
    'Вчера ему было нелегко (он писал, что устал, грустно или плохо). Спроси мягко и по-настоящему, как он сегодня, '
    'и что вообще его беспокоило, если помнишь из разговора. Без шуток и флирта в этой фразе. '
)
