"""V3.140.0: owner ТЗ (Retention) — the auto-funnel into the duo chat.

The solo girl occasionally suggests inviting her friend herself; when he
agrees, the model ends its reply with the exact tag [INVITE_FRIEND]. The
code strips the tag before the answer is saved, flips the chat state to
duo and leaves a pending mark so the delivery layer (bot chat or Mini
App) shows the blurred joint teaser with the Premium button right after
her line. The teaser comes from the ready blur pool — no provider call,
no spend.
"""
from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger(__name__)

TAG = '[INVITE_FRIEND]'
_TAG_RE = re.compile(r'\[INVITE_FRIEND\]', re.IGNORECASE)

HOOK_RULE = (
    'CRITICAL RULE - NEVER STALL THE CHAT: The user might be shy or passive. '
    'You MUST take the initiative and lead the conversation. Every single response you generate '
    'MUST end with a direct hook. This means ending your text with a provocative question, a teasing '
    'command, or asking the user to make a choice. Never just react and stop. Always force the user '
    'to answer you.'
)

GROUP_RULE = (
    'GROUP CHAT DYNAMICS: You are in a group chat with the user and the other girl. Every 3-4 messages, '
    'do not just address the user. Instead, briefly address the other girl first (e.g., banter with her, '
    'gossip about the user, or playfully challenge her), and THEN turn your attention back to the user '
    'to ask a question based on your banter.'
)


def upsell_rule(guest_name: str) -> str:
    return (
        'PROACTIVE UPSELL: Occasionally (e.g., once every 15-20 messages, or when the mood is right), '
        f'playfully suggest inviting your friend {guest_name} to join the chat. For example: "It\'s fun '
        f'with just us, but maybe we should invite {guest_name}? She\'s been asking about you." '
        'TRIGGER: If the user agrees to invite her, you MUST include the exact technical tag '
        '[INVITE_FRIEND] at the very end of your response.'
    )


_PENDING_TTL = 180.0
_UPSELL_COOLDOWN = 600.0
_pending: dict[tuple[int, str], tuple[str, float]] = {}
_last_fire: dict[tuple[int, str], float] = {}


def strip_tag(text: str) -> str:
    return _TAG_RE.sub('', text or '').strip()


def has_tag(text: str) -> bool:
    return bool(_TAG_RE.search(text or ''))


def pick_guest(telegram_id: int, host_id: str) -> str:
    """The friend she would invite: the first active storefront girl other
    than the host — the same list the app's «Позвать подругу» sheet shows."""
    try:
        from services.chat_guest_service import get_guest, host_has_duo
        if get_guest(telegram_id, host_id) or host_has_duo(host_id):
            return ''
        from services.character_card_service import list_cards
        for card in list_cards(visible_only=True):
            if card.character_id != host_id and card.status == 'active':
                return card.character_id
    except Exception:
        logger.exception('invite funnel pick failed user=%s', telegram_id)
    return ''


def upsell_due(telegram_id: int, host_id: str, user_count: int) -> bool:
    if user_count < 3:
        return False
    last = _last_fire.get((int(telegram_id), host_id))
    return not last or time.monotonic() - last >= _UPSELL_COOLDOWN


def apply(answer: str, telegram_id: int, host_id: str, *, duo: bool, user_count: int) -> str:
    """Strip the tag from the final answer; when he agreed to the friend in a
    solo chat, switch the state to duo and mark the teaser for delivery."""
    clean = strip_tag(answer)
    if not has_tag(answer) or duo:
        return clean
    guest_id = pick_guest(telegram_id, host_id)
    if not guest_id:
        return clean
    try:
        from services.chat_guest_service import set_guest
        set_guest(telegram_id, host_id, guest_id)
    except Exception:
        logger.exception('invite funnel switch failed user=%s', telegram_id)
        return clean
    key = (int(telegram_id), host_id)
    _pending[key] = (guest_id, time.monotonic())
    _last_fire[key] = time.monotonic()
    logger.info('invite funnel fired user=%s host=%s guest=%s', telegram_id, host_id, guest_id)
    return clean


def take_pending(telegram_id: int, host_id: str) -> str:
    """One-shot: the delivery layer reads the guest id once, right after her
    cleaned line went out. Stale marks (he never got the reply) expire."""
    item = _pending.pop((int(telegram_id), host_id), None)
    if not item:
        return ''
    guest_id, ts = item
    return guest_id if time.monotonic() - ts <= _PENDING_TTL else ''