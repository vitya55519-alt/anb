"""Bounded life experiment: durable assignment and text-free attribution.

Delivery/reply hooks participate in the caller's transaction. Assignment, explicit
opens, stops and evidence review own short transactions; reporting is read-only.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import math
import os
import re

from sqlalchemy import and_, distinct, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from models.app_models import (
    LifeEvent, LifeEventReply, LifeExperiment, LifeExperimentIssue,
    LifeParticipant, Message, User,
)
from services.db import SessionLocal

EXPERIMENT_KEY = 'life_participation_v1'
ENABLED = os.getenv('LIFE_EXPERIMENT_ENABLED', '1') == '1'
ENROLLMENT = timedelta(days=14)
REPLY_WINDOW = timedelta(hours=24)
RETURN_WINDOW = timedelta(days=7)
MIN_RECIPIENTS = 700
ARMS = ('control', 'treatment')


def _now(now=None):
    value = now if now is not None else datetime.now(timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _outside():
    return {'experiment_key': None, 'variant': 'outside'}


def _lock_user(session, uid):
    # A real UPDATE, not SQLite's ignored FOR UPDATE. It also opens a real
    # transaction before any nested savepoint in the legacy sqlite3 driver.
    return session.execute(
        update(User).where(User.id == uid).values(id=User.id),
        execution_options={'synchronize_session': False},
    ).rowcount == 1


def _lock_run(session, key=EXPERIMENT_KEY):
    session.execute(
        update(LifeExperiment).where(LifeExperiment.key == key)
        .values(key=LifeExperiment.key),
        execution_options={'synchronize_session': False},
    )
    return session.scalar(select(LifeExperiment).where(LifeExperiment.key == key)
                          .execution_options(populate_existing=True))


def _ensure_run(session, now, *, stopped=False, reason=None):
    run = _lock_run(session)
    if run is None:
        # Different users can reach the first assignment simultaneously. Only
        # the insert loses its savepoint, never the caller's outer transaction.
        try:
            with session.begin_nested():
                run = LifeExperiment(
                    key=EXPERIMENT_KEY, started_at=None if stopped else now,
                    status='stopped' if stopped else 'running',
                    stopped_at=now if stopped else None,
                    stop_reason=reason if stopped else None,
                )
                session.add(run)
                session.flush()
        except IntegrityError:
            run = _lock_run(session)
            if run is None:
                raise
    return run


def assignment(uid, *, now=None) -> dict:
    """Enroll only an already scheduler-eligible ordinary moment attempt."""
    if not ENABLED:
        return _outside()
    at = _now(now)
    with SessionLocal() as session, session.begin():
        if not _lock_user(session, uid):
            return _outside()
        run = _ensure_run(session, at)
        if (run.status != 'running' or run.started_at is None
                or not run.started_at <= at < run.started_at + ENROLLMENT):
            return _outside()
        participant = session.scalar(select(LifeParticipant).where(
            LifeParticipant.experiment_key == EXPERIMENT_KEY,
            LifeParticipant.user_id == uid,
        ))
        if participant is None:
            parity = int(hashlib.sha256(f'{EXPERIMENT_KEY}:{uid}'.encode('utf-8')).hexdigest(), 16) % 2
            participant = LifeParticipant(
                user_id=uid, experiment_key=EXPERIMENT_KEY,
                variant=ARMS[parity], assigned_at=at,
            )
            session.add(participant)
        return {'experiment_key': EXPERIMENT_KEY, 'variant': participant.variant}


def scene_enabled(session, event) -> bool:
    """Fresh run status, not a possibly stale identity-map object; no writes."""
    if (not ENABLED or event is None or event.variant != 'treatment'
            or event.kind != 'moment' or event.experiment_key != EXPERIMENT_KEY):
        return False
    with session.no_autoflush:
        status = session.scalar(select(LifeExperiment.status).where(
            LifeExperiment.key == event.experiment_key,
        ))
    return status == 'running'


def _participant(session, uid):
    return session.scalar(select(LifeParticipant).where(
        LifeParticipant.experiment_key == EXPERIMENT_KEY,
        LifeParticipant.user_id == uid,
    ).execution_options(populate_existing=True))


def record_delivery(session, message, context=None):
    """Record a flushed life message, without enrolling unassigned deliveries."""
    if (message.origin != 'life' or message.role != 'assistant'
            or message.id is None or message.created_at is None):
        return None
    if not _lock_user(session, message.user_id):
        return None
    existing = session.scalar(select(LifeEvent).where(LifeEvent.message_id == message.id)
                              .execution_options(populate_existing=True))
    if existing is not None:
        return existing

    context = context or {}
    kind = 'live_photo' if message.image_prompt or context.get('kind') == 'live_photo' else 'moment'
    variant, key, participant = 'outside', None, None
    if (kind == 'moment' and context.get('experiment_key') == EXPERIMENT_KEY
            and context.get('variant') in ARMS):
        participant = _participant(session, message.user_id)
        if participant is not None and participant.variant == context['variant']:
            # Keep the variant that generated this message, even if stop was
            # pressed during generation. Never retrospectively call it control.
            variant, key = participant.variant, participant.experiment_key
    at = _now(message.created_at)
    mode = context.get('mode_on')
    event = LifeEvent(
        user_id=message.user_id, character_id=message.character_id,
        message_id=message.id, kind=kind, experiment_key=key, variant=variant,
        mode_on=mode if isinstance(mode, bool) else None,
        delivered_at=at, reply_count=0, scene_status='pending',
    )
    # Serialize stop against creation of a new pending treatment scene.
    if variant == 'treatment':
        _lock_run(session, key)
    if not scene_enabled(session, event):
        event.scene_status = 'closed'
        event.closed_reason = ('disabled' if not ENABLED else
                               'stopped' if variant == 'treatment' else variant)

    pair = (LifeEvent.user_id == message.user_id,
            LifeEvent.character_id == message.character_id)
    older = or_(LifeEvent.delivered_at < at, and_(
        LifeEvent.delivered_at == at, LifeEvent.message_id < message.id))
    session.execute(update(LifeEvent).where(
        *pair, older, LifeEvent.variant == 'treatment',
        LifeEvent.scene_status != 'closed',
    ).values(scene_status='closed', closed_reason='superseded'),
        execution_options={'synchronize_session': 'fetch'})
    newer = session.scalar(select(LifeEvent.id).where(*pair, or_(
        LifeEvent.delivered_at > at,
        and_(LifeEvent.delivered_at == at, LifeEvent.message_id > message.id),
    )).limit(1))
    if variant == 'treatment' and newer is not None:
        event.scene_status, event.closed_reason = 'closed', 'superseded'
    session.add(event)
    session.flush()
    if key and participant.first_event_id is None:
        participant.first_event_id = event.id
        participant.first_mode = event.mode_on
    return event


def _mark_return(session, uid, cid, at, *, message_id=None):
    participant = _participant(session, uid)
    if participant is None or participant.first_event_id is None:
        return
    first = session.get(LifeEvent, participant.first_event_id)
    if (first is None or first.user_id != uid or first.character_id != cid
            or first.experiment_key != EXPERIMENT_KEY or first.kind != 'moment'
            or first.variant != participant.variant
            or (message_id is not None and message_id <= first.message_id)):
        return
    source = session.get(Message, first.message_id)
    if (source is None or source.user_id != uid or source.character_id != cid
            or source.role != 'assistant' or source.created_at != first.delivered_at):
        return
    if first.delivered_at + REPLY_WINDOW <= at < first.delivered_at + RETURN_WINDOW:
        if participant.returned_at is None or at < participant.returned_at:
            participant.returned_at = at


def record_reply(session, message):
    """Attribute an accepted input once to the latest preceding same-pair event."""
    if (message.origin != 'user_input' or message.role != 'user'
            or not (message.content or '').strip()
            or message.media_kind not in (None, '', 'voice')
            or (message.media_url and message.media_kind != 'voice')
            or message.image_prompt
            or message.id is None or message.created_at is None):
        return None
    if not _lock_user(session, message.user_id):
        return None
    previous = session.get(LifeEventReply, message.id)
    if previous is not None:
        return previous.event_id
    at = _now(message.created_at)
    # A day-2 input may count as return even when no event has a live 24h window.
    _mark_return(session, message.user_id, message.character_id, at, message_id=message.id)
    event = session.scalar(select(LifeEvent).join(
        Message, Message.id == LifeEvent.message_id,
    ).where(
        Message.role == 'assistant', Message.origin == 'life',
        Message.user_id == message.user_id, Message.character_id == message.character_id,
        LifeEvent.user_id == message.user_id,
        LifeEvent.character_id == message.character_id,
        LifeEvent.message_id < message.id,
        LifeEvent.delivered_at <= at,
        LifeEvent.delivered_at > at - REPLY_WINDOW,
    ).order_by(LifeEvent.delivered_at.desc(), LifeEvent.message_id.desc()).limit(1)
        .execution_options(populate_existing=True))
    if event is None:
        return None
    session.add(LifeEventReply(message_id=message.id, event_id=event.id,
                               user_id=message.user_id, created_at=at))
    event.reply_count += 1
    if event.first_reply_at is None or at < event.first_reply_at:
        event.first_reply_at = at
    if event.reply_count == 3:
        # Normally inputs arrive in order. In a delayed concurrent save, use the
        # timestamp of the third chronological input, not the last hook call.
        session.flush()
        times = session.scalars(select(LifeEventReply.created_at).where(
            LifeEventReply.event_id == event.id,
        ).order_by(LifeEventReply.created_at, LifeEventReply.message_id).limit(3)).all()
        event.engaged_at = times[2]
    elif event.reply_count > 3 and event.engaged_at is not None and at < event.engaged_at:
        session.flush()
        event.engaged_at = session.scalar(select(LifeEventReply.created_at).where(
            LifeEventReply.event_id == event.id,
        ).order_by(LifeEventReply.created_at, LifeEventReply.message_id).offset(2).limit(1))
    session.flush()
    return event.id


def record_open(uid, cid, *, now=None):
    """Only explicit open=1 callers invoke this; a reply never implies an open."""
    at = _now(now)
    with SessionLocal() as session, session.begin():
        if not _lock_user(session, uid):
            return 0
        _mark_return(session, uid, cid, at)
        result = session.execute(update(LifeEvent).where(
            LifeEvent.user_id == uid, LifeEvent.character_id == cid,
            LifeEvent.delivered_at <= at, LifeEvent.delivered_at > at - REPLY_WINDOW,
            LifeEvent.opened_at.is_(None),
        ).values(opened_at=at), execution_options={'synchronize_session': False})
        return result.rowcount


def _stop_run(run, reason, at):
    if run.status != 'stopped':
        run.status, run.stopped_at, run.stop_reason = 'stopped', at, reason


def stop(reason='manual', *, now=None):
    # Reason is an identifier, never arbitrary complaint/chat text.
    if not isinstance(reason, str) or not re.fullmatch(r'[a-zA-Z0-9_:-]{1,128}', reason):
        raise ValueError('Stop reason must be an identifier')
    at = _now(now)
    with SessionLocal() as session, session.begin():
        run = _ensure_run(session, at, stopped=True, reason=reason)
        _stop_run(run, reason, at)


def record_issue(event_id, message_id, kind, *, confirmed=False):
    """Review an evidence identifier; two distinct confirmed messages stop run."""
    if kind not in ('memory', 'intrusive'):
        raise ValueError('Unknown life issue kind')
    with SessionLocal() as session, session.begin():
        event = session.get(LifeEvent, event_id)
        evidence = session.execute(select(
            Message.user_id, Message.character_id, Message.created_at,
        ).where(Message.id == message_id)).first()
        if (event is None or evidence is None or message_id <= event.message_id
                or evidence.user_id != event.user_id
                or evidence.character_id != event.character_id
                or evidence.created_at < event.delivered_at):
            return None
        # Keep the same User -> run lock order as assignment/delivery. The
        # run lock serializes count+stop across users, even at first enrollment.
        if not _lock_user(session, event.user_id):
            return None
        run = _lock_run(session)
        issue = session.scalar(select(LifeExperimentIssue).where(
            LifeExperimentIssue.event_id == event_id,
            LifeExperimentIssue.message_id == message_id,
            LifeExperimentIssue.kind == kind,
        ))
        if issue is None:
            issue = LifeExperimentIssue(event_id=event_id, message_id=message_id,
                                        kind=kind, confirmed=bool(confirmed), created_at=_now())
            session.add(issue)
        elif confirmed:
            issue.confirmed = True
        session.flush()
        if run is not None and confirmed:
            incidents = session.scalar(select(func.count(distinct(LifeExperimentIssue.message_id)))
                .join(LifeEvent, LifeEvent.id == LifeExperimentIssue.event_id).where(
                    LifeEvent.experiment_key == EXPERIMENT_KEY,
                    LifeEvent.kind == 'moment', LifeEvent.variant.in_(ARMS),
                    LifeExperimentIssue.confirmed.is_(True),
                ))
            if incidents >= 2:
                _stop_run(run, 'repeated_quality_errors', _now())
        return issue.id


def review_due(*, now=None) -> bool:
    """True once enrollment is over and the day-14 review was never sent."""
    at = _now(now)
    with SessionLocal() as session:
        run = session.get(LifeExperiment, EXPERIMENT_KEY)
        return bool(run is not None and run.started_at is not None
                    and run.review_sent_at is None
                    and at >= run.started_at + ENROLLMENT)


def mark_review_sent(*, now=None) -> bool:
    """Claim the one-time review atomically; a duplicate send never happens."""
    at = _now(now)
    with SessionLocal() as session, session.begin():
        run = _lock_run(session)
        if (run is None or run.started_at is None or run.review_sent_at is not None
                or at < run.started_at + ENROLLMENT):
            return False
        run.review_sent_at = at
        return True


def recent_issues(limit: int = 10) -> list[dict]:
    """Admin review queue: identifiers only, never chat text."""
    with SessionLocal() as session:
        rows = session.scalars(select(LifeExperimentIssue).order_by(
            LifeExperimentIssue.confirmed, LifeExperimentIssue.id.desc()).limit(max(1, min(50, int(limit))))).all()
        return [{'id': r.id, 'event_id': r.event_id, 'message_id': r.message_id,
                 'kind': r.kind, 'confirmed': bool(r.confirmed), 'created_at': r.created_at} for r in rows]


def confirm_issue(issue_id: int) -> bool:
    """Admin confirms one reviewed incident; two distinct ones stop the run."""
    with SessionLocal() as session, session.begin():
        issue = session.get(LifeExperimentIssue, int(issue_id))
        if issue is None or issue.confirmed:
            return False
        event = session.get(LifeEvent, issue.event_id)
        if event is None or not _lock_user(session, event.user_id):
            return False
        run = _lock_run(session)
        issue.confirmed = True
        session.flush()
        if run is not None:
            incidents = session.scalar(select(func.count(distinct(LifeExperimentIssue.message_id)))
                .join(LifeEvent, LifeEvent.id == LifeExperimentIssue.event_id).where(
                    LifeEvent.experiment_key == EXPERIMENT_KEY,
                    LifeEvent.kind == 'moment', LifeEvent.variant.in_(ARMS),
                    LifeExperimentIssue.confirmed.is_(True),
                ))
            if incidents >= 2:
                _stop_run(run, 'repeated_quality_errors', _now())
        return True


def _wilson(successes, n):
    if not n:
        return None
    z = 1.959963984540054
    p, z2 = successes / n, z * z
    center = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, center - half), min(1.0, center + half)


def _comparison(arms):
    control, treatment = arms['control'], arms['treatment']
    if not control['n'] or not treatment['n']:
        return {'delta_pp': None, 'ci95_pp': None}
    c, t = control['rate'], treatment['rate']
    cl, cu = _wilson(control['engaged'], control['n'])
    tl, tu = _wilson(treatment['engaged'], treatment['n'])
    # Newcombe's unpooled difference of independent Wilson score intervals.
    lower = t - c - math.sqrt((t - tl) ** 2 + (cu - c) ** 2)
    upper = t - c + math.sqrt((tu - t) ** 2 + (c - cl) ** 2)
    return {'delta_pp': 100 * (t - c), 'ci95_pp': (100 * lower, 100 * upper)}


def _arm_report(participants, events_by_user, now):
    result = dict(assigned=len(participants), recipients=0, missing_deliveries=0,
                  deliveries=0, n=0, engaged=0, pending=0, pending_events=0,
                  return7d_n=0, return7d_count=0, mixed_mode=0,
                  opened_recipients=0, replied_recipients=0)
    for participant in participants:
        events = events_by_user.get(participant.user_id, [])
        if not events:
            result['missing_deliveries'] += 1
            continue
        result['recipients'] += 1
        result['deliveries'] += len(events)
        result['opened_recipients'] += int(any(e.opened_at is not None for e in events))
        result['replied_recipients'] += int(any(e.first_reply_at is not None for e in events))
        pending = sum(e.delivered_at + REPLY_WINDOW > now for e in events)
        if pending:
            # Exclude the WHOLE user, even if a previous event already won.
            result['pending'] += 1
            result['pending_events'] += pending
        else:
            result['n'] += 1
            result['engaged'] += int(any(e.reply_count >= 3 for e in events))
        modes = {e.mode_on for e in events if e.mode_on is not None}
        result['mixed_mode'] += int(len(modes) > 1)
        first = next((e for e in events if e.id == participant.first_event_id), None)
        if first is not None and first.delivered_at + RETURN_WINDOW <= now:
            result['return7d_n'] += 1
            returned = participant.returned_at
            result['return7d_count'] += int(returned is not None and
                first.delivered_at + REPLY_WINDOW <= returned < first.delivered_at + RETURN_WINDOW)
    result['rate'] = result['engaged'] / result['n'] if result['n'] else None
    result['ci95'] = _wilson(result['engaged'], result['n'])
    result['return7d_rate'] = (result['return7d_count'] / result['return7d_n']
                              if result['return7d_n'] else None)
    return result


def collect_report(*, now=None):
    """Read-only recipient analysis; assignments without delivery stay visible."""
    at = _now(now)
    with SessionLocal() as session:
        run = session.get(LifeExperiment, EXPERIMENT_KEY)
        participants = session.scalars(select(LifeParticipant).where(
            LifeParticipant.experiment_key == EXPERIMENT_KEY,
            LifeParticipant.assigned_at <= at,
        )).all()
        variants = {p.user_id: p.variant for p in participants}
        events_by_user = defaultdict(list)
        for event in session.scalars(select(LifeEvent).where(
            LifeEvent.experiment_key == EXPERIMENT_KEY,
            LifeEvent.kind == 'moment', LifeEvent.variant.in_(ARMS),
            LifeEvent.delivered_at <= at,
        )):
            if variants.get(event.user_id) == event.variant:
                events_by_user[event.user_id].append(event)
        arms = {arm: _arm_report([p for p in participants if p.variant == arm], events_by_user, at)
                for arm in ARMS}
        modes = {}
        for label, mode in (('off', False), ('on', True), ('unknown', None)):
            segmented = {arm: _arm_report(
                [p for p in participants if p.variant == arm and p.first_mode is mode],
                events_by_user, at) for arm in ARMS}
            modes[label] = {'arms': segmented, **_comparison(segmented)}
        start = run.started_at if run is not None else None
        deadline = start + ENROLLMENT if start is not None else None
        pending = sum(arm['pending'] for arm in arms.values())
        comparison = _comparison(arms)
        enrollment_complete = deadline is not None and at >= deadline
        sufficient = all(arm['n'] >= MIN_RECIPIENTS for arm in arms.values())
        outcome = 'inconclusive'
        if run is not None and run.status == 'stopped':
            outcome = 'stopped'
        elif ENABLED and enrollment_complete and not pending and sufficient:
            if comparison['delta_pp'] + 1e-12 < 5:
                outcome = 'target_not_met'
            elif comparison['ci95_pp'][0] > 0:
                outcome = 'success'
        return {
            'experiment_key': EXPERIMENT_KEY, 'enabled': ENABLED, 'as_of': at,
            'status': run.status if run is not None else 'not_started',
            'outcome': outcome, 'started_at': start, 'enrollment_deadline': deadline,
            'enrollment_complete': enrollment_complete, 'minimum_per_arm': MIN_RECIPIENTS,
            'stopped_at': run.stopped_at if run is not None else None,
            'stop_reason': run.stop_reason if run is not None else None,
            'pending': pending, 'pending_events': sum(a['pending_events'] for a in arms.values()),
            'mixed_mode': sum(a['mixed_mode'] for a in arms.values()),
            'arms': arms, 'modes': modes, **comparison,
        }


def render_report(data):
    """Compact Russian text for the existing weekly report, no notifications."""
    def date(value):
        return value.strftime('%d.%m.%Y %H:%M UTC') if value is not None else 'не начат'

    def rate(value):
        return f'{100 * value:.1f}%' if value is not None else '—'

    outcomes = {'success': 'цель достигнута', 'inconclusive': 'недостаточно данных',
                'target_not_met': 'цель не достигнута', 'stopped': 'остановлен'}
    lines = [f"Живые моменты: {outcomes[data['outcome']]}",
             f"Старт: {date(data['started_at'])}; набор до: {date(data['enrollment_deadline'])}"]
    for arm, label in (('control', 'Контроль'), ('treatment', 'Участие')):
        a = data['arms'][arm]
        lines.append(f"{label}: назначено {a['assigned']}, получателей {a['recipients']}, "
                     f"без доставки {a['missing_deliveries']}; открыли {a['opened_recipients']}, "
                     f"ответили {a['replied_recipients']}; ≥3 ответа {a['engaged']}/{a['n']} "
                     f"({rate(a['rate'])}), ждут 24ч {a['pending']}; "
                     f"возврат 7д {a['return7d_count']}/{a['return7d_n']} ({rate(a['return7d_rate'])})")
    if data['delta_pp'] is not None:
        low, high = data['ci95_pp']
        lines.append(f"Разница: {data['delta_pp']:+.1f} п.п.; 95% ДИ [{low:+.1f}; {high:+.1f}] п.п.")
    else:
        lines.append('Разница и 95% ДИ: пока нет зрелых получателей в обеих группах')
    for key, label in (('off', 'Режим выкл.'), ('on', 'Режим вкл.'), ('unknown', 'Режим неизвестен')):
        segment = data['modes'][key]['arms']
        if not any(a['assigned'] for a in segment.values()):
            continue
        c, t = segment['control'], segment['treatment']
        lines.append(f"{label} (первый): К {c['engaged']}/{c['n']} ({rate(c['rate'])}), "
                     f"У {t['engaged']}/{t['n']} ({rate(t['rate'])}); "
                     f"ждут 24ч {c['pending'] + t['pending']}")
    lines.append(f"Смена режима: {data['mixed_mode']}; минимум {data['minimum_per_arm']} "
                 'зрелых получателей/группу, 14 дней, прирост ≥5 п.п. и нижняя граница ДИ >0')
    if not data['enabled']:
        lines.append('Эксперимент выключен')
    if data['stop_reason']:
        lines.append(f"Причина остановки: {data['stop_reason']}")
    return '\n'.join(lines)
