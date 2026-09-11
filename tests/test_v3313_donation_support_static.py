"""Static regression tests for v3.31.3: «Support the project» donation link.

Owner request: add the CloudTips donation link to the welcome for every new
user, remind active users about once a week, and craft a message that motivates
a donation. The copy + CTA button live in services/donation_service.py, shared
by main.py (welcome) and services/scheduler_service.py (weekly job).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DONATION = (ROOT / 'services' / 'donation_service.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()

LINK = 'https://pay.cloudtips.ru/p/7afc7b16'


def test_version_bumped():
    assert VERSION in ('3.31.2', '3.31.3', '3.31.4', '3.31.5')


def test_config_donation_settings():
    assert f'DONATION_LINK = os.getenv("DONATION_LINK", "{LINK}").strip()' in CONFIG
    assert 'DONATION_REMINDER_ENABLED = os.getenv("DONATION_REMINDER_ENABLED", "true")' in CONFIG
    assert 'DONATION_REMINDER_INTERVAL_DAYS = max(1, int(os.getenv("DONATION_REMINDER_INTERVAL_DAYS", "7")))' in CONFIG
    assert 'DONATION_REMINDER_ACTIVE_DAYS = max(1, int(os.getenv("DONATION_REMINDER_ACTIVE_DAYS", "30")))' in CONFIG


def test_user_model_tracks_last_ping():
    assert 'last_donation_ping_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)' in MODELS


def test_donation_service_copy_and_cta():
    # motivating copy exists in both languages and the link rides on the button
    assert 'def donation_appeal(lang: str = RU) -> str:' in DONATION
    assert 'def donation_keyboard(lang: str = RU) -> InlineKeyboardMarkup:' in DONATION
    assert 'Поддержать проект' in DONATION
    assert 'Support the project' in DONATION
    assert 'url=DONATION_LINK' in DONATION
    # the message frames the donation as optional (never a hard sell)
    assert 'не обязательно' in DONATION
    assert "never required" in DONATION


def test_donation_service_weekly_gate():
    # only active, opted-in, 18+ users are due; gated by the per-user interval
    assert 'def due_donation_pings(now: dt.datetime)' in DONATION
    assert 'def mark_donation_ping_sent(user_id: int, now: dt.datetime)' in DONATION
    assert 'User.proactive_enabled == True' in DONATION
    assert 'User.adult_confirmed == True' in DONATION
    assert 'User.last_active_at >= active_cutoff' in DONATION
    assert 'if last is None or last <= ping_cutoff:' in DONATION
    assert 'user.last_donation_ping_at = now' in DONATION


def test_welcome_sends_donation_to_new_users():
    assert 'from services import donation_service' in MAIN
    consent = MAIN[MAIN.index('@dp.callback_query(F.data == \'consent:accept\')'):]
    consent = consent[:consent.index('@dp.callback_query(F.data == \'consent:terms\')')]
    assert 'donation_service.donation_appeal(lang)' in consent
    assert 'donation_service.donation_keyboard(lang)' in consent
    # guarded so a donation-send failure never breaks onboarding
    assert 'donation welcome message failed' in consent


def test_scheduler_registers_weekly_reminder():
    assert 'from services import donation_service' in SCHED
    assert 'DONATION_LINK, DONATION_REMINDER_ENABLED,' in SCHED
    assert 'async def _donation_reminder(bot):' in SCHED
    body = SCHED[SCHED.index('async def _donation_reminder(bot):'):]
    body = body[:body.index('def start_scheduler(bot):')]
    assert 'donation_service.due_donation_pings' in body
    assert 'donation_service.mark_donation_ping_sent' in body
    assert "track_event(uid, 'donation_reminder_sent'" in body
    # registered behind the enabled+link guard
    assert "scheduler.add_job(_donation_reminder,'interval',hours=12,args=[bot],id='donation_reminder',replace_existing=True)" in SCHED
    assert 'if DONATION_REMINDER_ENABLED and DONATION_LINK:' in SCHED
