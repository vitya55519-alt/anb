"""V3.90.0: the support desk (@Anna67901support_bot) done properly.

Owner's screenshot: every message — even /start and his own /admin — got the
same «Приняла твоё обращение ✅», appeals were plain forwards he could not
answer from the bot, and nothing told the user what to do meanwhile.

Now:
- /start shows a short menu of ready answers (payment, Premium, peaches,
  «она не отвечает», 18+ photos, deleting data) and «✍️ Написать менеджеру»;
- an appeal reaches the admins as a card (who, Premium, peaches, latest
  payments) with his message copied under it;
- an admin answers by replying to the card or to the copied message (or
  /reply <id> <text>); the user gets «💬 Ответ поддержки»;
- /tickets lists appeals still waiting for an answer (kept as product
  events, so a redeploy does not lose them);
- the «принято» ack goes out once per half hour, not on every message.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

APPEAL_EVENT = 'support_appeal'
ANSWER_EVENT = 'support_answer'
ACK_EVERY = timedelta(minutes=30)

from config import SUPPORT_WELCOME_TEXT as WELCOME  # noqa: E402

ACK = ('Приняли твоё обращение ✅ Менеджер ответит прямо в этом чате, обычно в течение дня. '
       'Если вопрос про оплату, пришли скриншот чека — так проверим быстрее.')

ANSWER_PREFIX = '💬 Ответ поддержки:\n\n'

# key -> (button, answer)
FAQ: dict[str, tuple[str, str]] = {
    'pay': ('💳 Оплатил, но ничего не пришло', (
        'Premium и персики обычно приходят в течение 1–2 минут после оплаты.\n\n'
        '1. Открой бота и нажми /start — статус обновится.\n'
        '2. В приложении потяни экран вниз или открой его заново.\n\n'
        'Прошло больше 10 минут? Напиши сюда и пришли скриншот чека (сумма, дата, время) — '
        'мы проверим платёж и начислим вручную. Деньги не потеряются.'
    )),
    'premium': ('⭐ Что даёт Premium', (
        'Premium открывает:\n'
        '• безлимит сообщений — она не «засыпает» посреди разговора\n'
        '• всё откровенное: пошлую переписку, фото «Наедине», «Раздеть», тайное видео\n'
        '• голосовые ответы и уровни отношений 7–10\n'
        '• выбор любого уровня общения 1–10 с каждой девушкой\n'
        '• персики в подарок каждый месяц\n\n'
        'Оформить можно в боте: кнопка «⭐ Premium» или вкладка «Магазин» в приложении.'
    )),
    'peaches': ('🍑 Персики: где взять и на что', (
        'Персики — внутренняя валюта: фото в чате, кружочки, картинки и видео в студии.\n\n'
        'Бесплатно: ежедневные задания (вкладка «Задания»), подписка на канал, '
        'приглашение друга (по 1000 🍑 вам обоим, когда он напишет ей 10 сообщений).\n'
        'Купить: вкладка «Магазин» в приложении.\n\n'
        'Если персики списались, а фото не пришло — напиши сюда, вернём.'
    )),
    'broken': ('🤐 Она не отвечает / ошибка', (
        'Подожди минуту и отправь сообщение ещё раз — иногда ответ генерируется дольше обычного. '
        'Если не помогло, нажми /start в боте.\n\n'
        'Без Premium есть дневной лимит сообщений: когда он закончится, она «засыпает» до завтра.\n\n'
        'Если ошибка повторяется — напиши сюда, что ты нажимал и что увидел (скриншот очень поможет).'
    )),
    'spicy': ('🔞 Почему нет откровенных фото', (
        'Откровенная переписка, фото «Наедине», «Раздеть» и тайное видео — только с Premium '
        'и после подтверждения 18+ в боте.\n\n'
        'Фото, которые ты загружаешь сам (реальные люди), мы никогда не раздеваем — это запрещено.'
    )),
    'delete': ('🗑 Удалить мои данные', (
        'Отправь команду /delete_me в основном боте — переписка и память удалятся. '
        'Если что-то не получилось, напиши сюда.'
    )),
}
WRITE_KEY = 'write'
WRITE_BUTTON = '✍️ Написать менеджеру'
WRITE_ANSWER = ('Напиши свой вопрос одним сообщением (можно со скриншотом) — '
                'менеджер ответит прямо здесь.')

_ID_RE = re.compile(r'\bid[:\s]+(\d{4,})')


def user_id_from_card(text: str | None) -> int | None:
    """The user's Telegram id written on an appeal card («id: 123…»)."""
    m = _ID_RE.search(text or '')
    return int(m.group(1)) if m else None


def parse_reply_command(text: str) -> tuple[int, str] | None:
    """«/reply 123456 текст» -> (123456, 'текст')."""
    m = re.match(r'^/reply(?:@\w+)?\s+(\d{4,})\s+(.+)$', (text or '').strip(), re.S)
    return (int(m.group(1)), m.group(2).strip()) if m else None


def _fmt_dt(dt: datetime | None) -> str:
    return dt.strftime('%d.%m %H:%M') if dt else '—'


def user_card(telegram_id: int, name: str, username: str | None, text: str) -> str:
    """The admin's card for one appeal: who he is and his money trail."""
    lines = [f'🆘 Обращение от {name or "без имени"}'
             + (f' (@{username})' if username else '') + f'\nid: {telegram_id}']
    try:
        from sqlalchemy import select
        from models.app_models import PlategaOrder, StarTransaction, Subscription
        from services.access_service import is_premium
        from services.db import SessionLocal
        from services.payments import get_photo_credits
        from services.user_service import get_user
        user = get_user(telegram_id)
        if user is None:
            lines.append('в основном боте не зарегистрирован')
        else:
            prem = is_premium(telegram_id)
            with SessionLocal() as s:
                sub = s.scalar(select(Subscription).where(Subscription.user_id == user.id)
                               .order_by(Subscription.expires_at.desc()).limit(1))
                orders = s.scalars(select(PlategaOrder).where(PlategaOrder.telegram_id == int(telegram_id))
                                   .order_by(PlategaOrder.id.desc()).limit(3)).all()
                stars = s.scalars(select(StarTransaction).where(StarTransaction.user_id == user.id)
                                  .order_by(StarTransaction.id.desc()).limit(2)).all()
            lines.append(f'Premium: {"да, до " + _fmt_dt(sub.expires_at) if prem and sub else "нет"}'
                         f' · 🍑 {get_photo_credits(telegram_id)}')
            lines.append(f'с нами с {_fmt_dt(user.created_at)}'
                         + (f' · источник {user.source_tag}' if user.source_tag else ''))
            for o in orders:
                lines.append(f'💳 {_fmt_dt(o.created_at)} {o.product} {o.amount} ₽ — {o.status}')
            for t in stars:
                lines.append(f'⭐ {_fmt_dt(t.created_at)} {t.product} {t.stars}⭐ ({t.provider})')
    except Exception:
        lines.append('(данные пользователя не загрузились)')
    if text:
        lines.append('\n' + text[:1500])
    lines.append('\n↩️ Ответь на это сообщение, и ответ уйдёт пользователю.')
    return '\n'.join(lines)


def _db_uid(telegram_id: int) -> int | None:
    from services.user_service import get_user
    user = get_user(telegram_id)
    return user.id if user else None


def note_event(event: str, telegram_id: int, text: str = '') -> None:
    try:
        from models.app_models import ProductEvent
        from services.db import SessionLocal
        with SessionLocal() as s:
            s.add(ProductEvent(user_id=_db_uid(telegram_id), event_name=event,
                               metadata_json=json.dumps({'tid': int(telegram_id), 'text': (text or '')[:300]},
                                                        ensure_ascii=False),
                               created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
            s.commit()
    except Exception:
        pass


def open_tickets(days: int = 7, limit: int = 15) -> list[dict]:
    """Appeals newer than the last answer to that user, newest first."""
    from sqlalchemy import select
    from models.app_models import ProductEvent
    from services.db import SessionLocal
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    with SessionLocal() as s:
        rows = s.scalars(select(ProductEvent).where(
            ProductEvent.event_name.in_((APPEAL_EVENT, ANSWER_EVENT)),
            ProductEvent.created_at >= since).order_by(ProductEvent.created_at)).all()
    state: dict[int, dict] = {}
    for r in rows:
        try:
            meta = json.loads(r.metadata_json or '{}')
            tid = int(meta['tid'])
        except Exception:
            continue
        if r.event_name == ANSWER_EVENT:
            state.pop(tid, None)
        else:
            state[tid] = {'tid': tid, 'text': meta.get('text', ''), 'at': r.created_at}
    return sorted(state.values(), key=lambda x: x['at'], reverse=True)[:limit]


def tickets_text(items: list[dict]) -> str:
    if not items:
        return 'Открытых обращений нет ✅'
    out = [f'Ждут ответа: {len(items)}']
    for t in items:
        out.append(f'• {_fmt_dt(t["at"])} id: {t["tid"]} — {(t["text"] or "(медиа)")[:80]}')
    out.append('\nОтветить: /reply <id> <текст>')
    return '\n'.join(out)
